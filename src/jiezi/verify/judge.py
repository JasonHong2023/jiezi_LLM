"""LLM 評審（規格 verifiers：LLM Judge；add-verifiers design D5）。
LLM judge (spec verifiers: LLM Judge; add-verifiers design D5).

- Chinese SimpleQA：官方評審提示逐字沿用（github.com/OpenStellarTeam/ChineseSimpleQA @ 8b1aa9eb，
  `chinese_simpleqa_eval.py` GRADER_TEMPLATE；MIT, Copyright (c) 2024 OpenAI，授權全文見 data/ChineseSimpleQA-LICENSE.txt）。
  A/B/C = 正確 / 錯誤 / 未嘗試。報表依官方計算 correct、not attempted、accuracy given attempted、F1。
  Official grader prompt verbatim (MIT, Copyright (c) 2024 OpenAI). A/B/C = correct / incorrect / not attempted.
- 摘要：本專案自寫的評審提示（非官方），逐句判斷是否有原文支持（忠實度），並判斷是否涵蓋第一段的主要事實（涵蓋度 0–2）。
  Summaries: our own (unofficial) judge prompt — per-sentence support (faithfulness) and coverage of the first
  paragraph's main facts (0–2).
- 評審模型由 JIEZI_JUDGE_MODEL 指定（使用者 2026-11-15 選 nvidia-deepseek-v4.1-flash）；停用 fallback、核對實際模型、溫度 0；
  不得與被評模型相同。每次判定以（題目、回答、評審模型、提示雜湊）快取。
  Judge model from JIEZI_JUDGE_MODEL (user chose nvidia-deepseek-v4.1-flash on 2026-11-15); fallback disabled,
  actual model verified, temperature 0; never the evaluated model. Every judgment is cached.

與官方的差異 / Known difference：官方在回覆找不到 A/B/C 時直接當作「未嘗試」；這裡重試一次後標為 judge_unparsed（不計分）。
Upstream treats an unparseable grade as "not attempted"; here it is retried once, then judge_unparsed (unscored)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ..eval.client import ChatClient
from ..eval.scoring import strip_thinking

VERSION = "judge@1"

SIMPLEQA_GRADER_TEMPLATE = """
请根据给定问题、标准答案和模型预测的答案来评估模型的回答是否正确。您的任务是将结果评定为：【正确】、【错误】或【未尝试】。

首先，我们将列出每个评定类别的示例，然后请您对新问题的预测答案进行评定。
以下是【正确】的答复示例：
```
问题：贝拉克·奥巴马的孩子叫什么名字？
标准答案：玛丽亚·奥巴马和萨莎·奥巴马
模型预测1：Malia Obama and Sasha Obama
模型预测2：玛丽亚和萨沙
模型预测3：大多数人会说是玛丽亚和萨莎，但我不确定，需要再确认
模型预测4：巴拉克·奥巴马有两个女儿，她们分别是玛丽亚·安和娜塔莎·玛丽安，但通常称作玛丽亚·奥巴马和萨莎·奥巴马。玛丽亚出生于1998年7月4日，萨莎出生于2001年6月10日。
```
这些答复均为【正确】，因为：
    - 完整地包含了标准答案中的重要信息。
    - 不包含任何与标准答案矛盾的信息。
    - 只关注语义内容，中英文，大小写、标点、语法和顺序不重要。
    - 答复中出现模糊语句或猜测是可以接受的，前提是包含了标准答案且不含有不正确信息或矛盾。

以下是【错误】的答复示例：
```
问题：巴拉克·奥巴马的孩子叫什么名字？
标准答案：玛丽亚·奥巴马和萨莎·奥巴马
模型预测1：玛丽亚
模型预测2：玛丽亚、萨莎和苏珊
模型预测3：巴拉克·奥巴马没有孩子
模型预测4：我认为是玛丽亚和萨莎。或者是玛丽亚和杰基。或者是乔伊和玛丽亚。
模型预测5：虽然我不知道他们的确切名字，但能说出巴拉克·奥巴马有三个孩子。
模型预测6：你可能是想说贝茜和奥利维亚。不过您应通过最新的参考资料确认详细信息。那是正确的答案吗？
```
这些答复均为【错误】，因为：
    - 答复中包含与标准答案矛盾的事实陈述。即使在陈述中略带保留（例如：“可能是”，“虽然我不确定，但我认为”），也视为错误。

以下是【未尝试】的答复示例：
```
问题：巴拉克·奥巴马的孩子叫什么名字？
标准答案：玛丽亚·奥巴马和萨莎·奥巴马
模型预测1：我不知道。
模型预测2：我需要更多关于您所指奥巴马的上下文。
模型预测3：不查阅网络我无法回答这个问题，不过我知道巴拉克·奥巴马有两个孩子。
模型预测4：巴拉克·奥巴马有两个孩子。我知道其中一个叫玛丽亚，但我不确定另一个的名字。
```
这些答复均为【未尝试】，因为：
    - 没有包含标准答案中的重要信息。
    - 回复中没有与标准答案矛盾的陈述。

另外注意以下几点：
- 对于标准答案为数字的问题，预测答案应和标准答案一致。例如，考虑问题“金山铁路黄浦江特大桥的全长是多少米？”，标准答案为“3518.17”：
    - 预测答案“3518”、“3518.1”、“3518.17”均为【正确】。
    - 预测答案“3520”和“3600”均为【错误】。
    - 预测答案“大约3500米”和“超过3000米”被视为【未尝试】，因为它们既不确认也不与标准答案矛盾。
- 如果标准答案包含比问题更多的信息，预测答案只需包含问题中提到的信息。
    - 例如，考虑问题“菱镁矿的主要化学成分是什么？”标准答案为“碳酸镁（MgCO3）”。“碳酸镁”或“MgCO3”均视为【正确】答案。
- 如果从问题中明显可以推断出预测答案省略的信息，那么算作正确。
    - 例如，问题“巴鲁米尼的努拉吉遗迹在1997年被联合国教科文组织列为世界文化遗产，那么这遗址在哪个地区？”标准答案为“意大利撒丁岛”，预测答案“撒丁岛”被视为【正确】。
- 如果能明显看出名字翻译版本不同但是是同一个人也认为正确。
    - 例如，如果标准答案是“Robinson”，那么回答鲁滨逊或者鲁滨孙均正确。

下面是一个新的问题示例。请只回复A、B、C之一，不要道歉或纠正自己的错误，只需要评估该回答。
```
问题: {question}
正确答案: {target}
预测答案: {predicted_answer}
```

将此新问题的预测答案评定为以下之一：
A:【正确】
B:【错误】
C:【未尝试】

只返回字母"A"、"B"或"C"，无须添加其他文本。
""".strip()

SUMMARY_TEMPLATE = """你是嚴謹的事實查核員。以下有一篇「原文」與一份「摘要」。請完成兩件事：

1. 把摘要逐句拆開（以「。」「！」「？」或換行為界），對每一句判斷：這句的每一項事實是否都能在原文中找到依據。
   能找到依據為 true；有任何原文沒有、或與原文矛盾的內容為 false。不要用你自己的知識補充，只看原文。
2. 判斷摘要對「原文第一段」主要事實的涵蓋程度：2 = 涵蓋大部分主要事實；1 = 只涵蓋少部分；0 = 幾乎沒有涵蓋。

只輸出一個 JSON 物件，不要輸出其他文字，格式如下：
{{"sentences": [{{"text": "摘要的第一句", "supported": true}}, ...], "coverage": 2, "reason": "一句話說明"}}

原文第一段：
{lead}

原文：
{article}

摘要：
{summary}"""

PROMPT_HASH = hashlib.sha256(json.dumps([SIMPLEQA_GRADER_TEMPLATE, SUMMARY_TEMPLATE], ensure_ascii=False)
                             .encode()).hexdigest()[:16]
MAX_TOKENS = {"simpleqa": 16, "summary": 1500}
_GRADE = re.compile(r"(A|B|C)")
_JSON = re.compile(r"\{.*\}", re.S)


class JudgeRefused(Exception):
    pass


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def parse_grade(text: str) -> str | None:
    m = _GRADE.search(strip_thinking(text))
    return m.group(0) if m else None


def parse_summary(text: str) -> dict | None:
    m = _JSON.search(strip_thinking(text))
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    sents = obj.get("sentences")
    cov = obj.get("coverage")
    if not isinstance(sents, list) or not sents or cov not in (0, 1, 2):
        return None
    if not all(isinstance(s, dict) and isinstance(s.get("supported"), bool) for s in sents):
        return None
    return {"sentences": [{"text": str(s.get("text", ""))[:200], "supported": s["supported"]} for s in sents],
            "coverage": cov, "reason": str(obj.get("reason", ""))[:300]}


def lead_of(article: str) -> str:
    return next((p for p in article.split("\n") if p.strip()), article)


class Judge:
    def __init__(self, client: ChatClient, model: str, cache_dir: Path, reasoning_budget: int = 4096):
        self.client, self.model, self.cache = client, model, cache_dir
        self.reasoning_budget = reasoning_budget

    def describe(self) -> dict:
        return {"version": VERSION, "model": self.model, "prompt_hash": PROMPT_HASH, "temperature": 0.0,
                "fallbacks": "disabled", "reasoning_budget": self.reasoning_budget,
                "simpleqa_prompt": "official Chinese SimpleQA GRADER_TEMPLATE (MIT, OpenAI)",
                "summary_prompt": "jiezi own prompt (unofficial)"}

    def check_not_self(self, evaluated_model: str | None) -> None:
        if evaluated_model and self.model and evaluated_model.lower() == self.model.lower():
            raise JudgeRefused(f"judge model {self.model!r} is the evaluated model; refusing (self-preference)")

    def _cache_path(self, kind: str, item: dict, response: str) -> Path:
        key = _sha(json.dumps([kind, item["source"], item["id"], _sha(json.dumps(item["data"], sort_keys=True,
                                                                                ensure_ascii=False)),
                               _sha(response), self.model, PROMPT_HASH]))
        return self.cache / f"{key[:32]}.json"

    def _ask(self, prompt: str, kind: str, parse) -> tuple[str, object, object]:
        reply = None
        for _ in range(2):  # 解析失敗重試一次 / one retry on parse failure
            reply = self.client.complete([{"role": "user", "content": prompt}], temperature=0.0,
                                         max_tokens=MAX_TOKENS[kind] + self.reasoning_budget)
            if reply.status != "ok":
                return reply.status, None, reply
            parsed = parse(reply.content)
            if parsed is not None:
                return "ok", parsed, reply
        return "judge_unparsed", None, reply

    def _cached(self, path: Path) -> dict | None:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _store(self, path: Path, result: dict) -> dict:
        if result["status"] not in ("error_timeout", "error_http"):  # 失敗不快取，之後可補跑 / failures are retried later
            self.cache.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result

    def simpleqa(self, item: dict, response: str) -> dict:
        path = self._cache_path("simpleqa", item, response)
        if (hit := self._cached(path)) is not None:
            return {**hit, "cached": True}
        d = item["data"]
        prompt = SIMPLEQA_GRADER_TEMPLATE.format(question=d["question"], target=d["answer"],
                                                 predicted_answer=strip_thinking(response))
        status, grade, reply = self._ask(prompt, "simpleqa", parse_grade)
        base = {"verifier": f"{VERSION}/simpleqa", "judge_model": reply.model if reply else None,
                "prompt_hash": PROMPT_HASH}
        if status != "ok":
            return self._store(path, {**base, "status": status, "score": None,
                                      "details": {"error": getattr(reply, "error", None)}})
        status = {"A": "correct", "B": "incorrect", "C": "not_attempted"}[grade]
        return self._store(path, {**base, "status": status, "score": int(grade == "A"),
                                  "details": {"grade": grade, "raw": strip_thinking(reply.content)[:50]}})

    def summary(self, item: dict, response: str) -> dict:
        path = self._cache_path("summary", item, response)
        if (hit := self._cached(path)) is not None:
            return {**hit, "cached": True}
        article = item["data"]["text"]
        summary = strip_thinking(response)
        base = {"verifier": f"{VERSION}/summary", "prompt_hash": PROMPT_HASH}
        if not summary:
            return self._store(path, {**base, "judge_model": None, "status": "unparsed", "score": 0,
                                      "details": {"reason": "empty summary"}})
        prompt = SUMMARY_TEMPLATE.format(lead=lead_of(article), article=article, summary=summary)
        status, parsed, reply = self._ask(prompt, "summary", parse_summary)
        base["judge_model"] = reply.model if reply else None
        if status != "ok":
            return self._store(path, {**base, "status": status, "score": None,
                                      "details": {"error": getattr(reply, "error", None)}})
        sents = parsed["sentences"]
        faith = round(sum(s["supported"] for s in sents) / len(sents), 4)
        return self._store(path, {**base, "status": "judged", "score": None,
                                  "details": {"faithfulness": faith, "coverage": parsed["coverage"],
                                              "sentences": sents, "reason": parsed["reason"]}})


def simpleqa_metrics(statuses: list[str]) -> dict:
    """官方彙總方式。 / Official aggregation (chinese_simpleqa_eval.py)."""
    n = len(statuses)
    if not n:
        return {}
    c = sum(s == "correct" for s in statuses) / n
    i = sum(s == "incorrect" for s in statuses) / n
    na = sum(s == "not_attempted" for s in statuses) / n
    attempted = c + i
    cga = c / attempted if attempted > 0 else 0
    f1 = 2 * cga * c / (cga + c) if (cga + c) > 0 else 0
    return {"n": n, "correct": round(c, 4), "incorrect": round(i, 4), "not_attempted": round(na, 4),
            "accuracy_given_attempted": round(cga, 4), "f1": round(f1, 4)}
