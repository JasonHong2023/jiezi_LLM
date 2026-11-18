"""老師模型：轉交過的題目在背景問免費的老師模型，答案一致才存成訓練資料（add-open-teacher）。
Teacher models: escalated questions are asked again to free teacher models in the background; agreeing answers
become training data (add-open-teacher).

使用者 2026-11-18：「老師不只一個」「我不要管條款，能用的模型就用，我只能用免費的」。所以老師清單用 LiteLLM 上免費的模型，
條款沒查證的也用（使用者決定承擔，記在 docs/licenses.md）；只排除條款**明文禁止**用輸出訓練其他模型的服務：
Anthropic（Claude）、Google（Gemini）、OpenAI 的商業 API（GPT-4o 等）。Claude 的回答只用來把關。
The user chose to use any free model, verified or not; services whose terms explicitly forbid training on outputs
(Anthropic, Google Gemini, OpenAI's commercial API) are always excluded. Claude answers are used only as a check."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

# 條款明文禁止用輸出訓練其他模型：不論設定都不當老師 / never teachers, whatever the configuration
FORBIDDEN = re.compile(r"claude|anthropic|gemini|google|gpt-4|gpt-5|openai/gpt-(?!oss)|o[134]-|chatgpt", re.I)
MAX_TOKENS = 1500
DAILY_MAX = 100
AGREE = 0.5          # 關鍵事實重疊 / overlap of key facts
TEXT_AGREE = 0.3     # 沒有關鍵事實時，文字相似度 / text similarity when there are no key facts


def allowed(model: str) -> bool:
    return bool(model) and not FORBIDDEN.search(model)


def facts(text: str) -> set[str]:
    """關鍵事實：數字（含年份、日期）、粗體或引號裡的名稱。 / Key facts: numbers and bold or quoted names."""
    t = text or ""
    nums = {n.lstrip("0") or "0" for n in re.findall(r"\d+(?:\.\d+)?", t) if len(n) >= 2}
    names = {x.strip() for x in re.findall(r"\*\*(.{1,30}?)\*\*|「(.{1,30}?)」|《(.{1,30}?)》", t) for x in x if x}
    return nums | {n for n in names if n}


def agree(a: str, b: str, question: str = "") -> bool:
    """關鍵事實（扣掉題目本身就有的，例如題目裡的年份）重疊夠多就算一致。
    Agreement on key facts, ignoring facts already in the question (such as its year)."""
    known = facts(question)
    fa, fb = facts(a) - known, facts(b) - known
    if fa and fb:
        return len(fa & fb) / max(1, min(len(fa), len(fb))) >= AGREE
    from .memory import similarity
    return similarity(a[:400], b[:400]) >= TEXT_AGREE


def usage_path(root: Path) -> Path:
    return Path(root) / "var" / "training" / "teacher-usage.json"


def take(root: Path, model: str, daily_max: int = DAILY_MAX) -> bool:
    """今天這位老師還有額度就扣一次。 / Use one of today's questions for this teacher if any are left."""
    p = usage_path(root)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    today = date.today().isoformat()
    day = data.get(today, {})
    if day.get(model, 0) >= daily_max:
        return False
    day[model] = day.get(model, 0) + 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({today: day}, ensure_ascii=False), encoding="utf-8")
    return True


def out_path(root: Path) -> Path:
    return Path(root) / "var" / "training" / "teacher.jsonl"


def judge(answers: dict[str, str], delivered: str, question: str = "") -> dict[str, str]:
    """每位老師的答案要和交付的答案、或另一位老師一致才收；回傳 {老師: 一致的對象}。
    A teacher's answer is kept when it agrees with the delivered answer or another teacher."""
    kept = {}
    for m, a in answers.items():
        if not a.strip():
            continue
        if delivered and agree(a, delivered, question):
            kept[m] = "delivered"
            continue
        other = next((o for o, b in answers.items() if o != m and b.strip() and agree(a, b, question)), None)
        if other:
            kept[m] = f"teacher:{other}"
    return kept


def save(root: Path, messages: list[dict], answer: str, teacher: str, agreed: str, trajectory_id: str) -> None:
    from .training_data import _ex
    ex = _ex([m for m in messages if m.get("role") in ("system", "user", "assistant")], answer, "teacher",
             f"teacher-output ({teacher}; 使用者 2026-11-18 決定使用，條款見 docs/licenses.md)", "teacher",
             teacher=teacher, agreed_with=agreed, trajectory_id=trajectory_id)
    p = out_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ex, ensure_ascii=False) + "\n")


def load(root: Path) -> list[dict]:
    p = out_path(root)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
