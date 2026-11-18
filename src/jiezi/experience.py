"""經驗：本機解題過程的教訓（local-first-solving；使用者 2026-11-18：「這些解決的過程他要記錄下來變成經驗」）。
Experience: lessons from how a question was finally solved (local-first-solving).

每筆一個 Markdown 檔，放在記憶 wiki 的 `experience/`（Obsidian 可以看、改、刪）。記「題目、第一次錯在哪、哪一步解決、
最後答案的重點、下次要注意什麼」——不管最後是本機、雲端或 Claude 解決的都記（使用者 2026-11-18：「我要芥子跟你請教
就是要她記憶」）。相似題目作答前附上相關經驗；用了答對記一次有效，用了還是不行記一次無效，無效三次就停用。
經驗是記憶，不是訓練資料（訓練資料另依服務條款，見 R6.8）。
One Markdown file per lesson under the memory wiki's `experience/`: the question, what failed, which step solved it, the
key points of the final answer (whoever solved it) and a short lesson. Memory, not training data. Similar questions get the lesson as a hint;
uses are counted and a lesson is disabled after three failures."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .memory import similarity

DIR = "experience"
MATCH = 0.35          # 附上經驗的相似度 / similarity to attach a lesson
SAME = 0.6            # 視為同一種題目、合併計數 / same kind of question: merge
MAX_HINTS = 2
FAIL_LIMIT = 3
LESSON_MAX = 300
STEPS = {"retry": "帶著錯誤重答", "think": "思考模式重答", "hint": "依雲端提示重答", "claude": "請教 Claude",
         "cloud": "雲端模型回答"}


@dataclass
class Lesson:
    id: str
    question: str
    error: str
    step: str
    lesson: str
    at: str
    seen: int = 1
    uses: int = 0
    wins: int = 0
    fails: int = 0
    disabled: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return not self.disabled and self.fails < FAIL_LIMIT


def _slug(text: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|#\[\]\n\r\t]", "", text).strip()[:40] or "experience"
    return s


class Experience:
    """經驗庫；同一時間只有一個寫入者（gateway 內鎖住）。 / The lesson store; writes are serialised."""

    def __init__(self, wiki: Path):
        self.dir = Path(wiki) / DIR
        self.lock = threading.Lock()

    # ── 讀寫 / storage ──
    def _path(self, lid: str) -> Path:
        return self.dir / f"{lid}.md"

    def load(self) -> list[Lesson]:
        out = []
        for p in sorted(self.dir.glob("*.md")) if self.dir.is_dir() else []:
            m = re.search(r"<!-- jiezi:(\{.*\}) -->", p.read_text(encoding="utf-8"), re.S)
            if not m:
                continue
            try:
                d = json.loads(m.group(1))
                # 使用者在 Obsidian 改過「教訓」段落就用改過的 / a lesson edited in Obsidian wins
                body = p.read_text(encoding="utf-8")
                edited = re.search(r"## 下次要注意\n\n(.+?)\n\n", body, re.S)
                if edited:
                    d["lesson"] = edited.group(1).strip()
                out.append(Lesson(**{k: v for k, v in d.items() if k in Lesson.__dataclass_fields__}))
            except (ValueError, TypeError):
                continue
        return out

    def _write(self, e: Lesson) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        state = "停用" if not e.active else "使用中"
        text = (f"# 經驗：{e.question[:60]}\n\n"
                f"- 題目：{e.question}\n- 第一次錯在：{e.error}\n- 解決的步驟：{STEPS.get(e.step, e.step)}\n"
                f"- 遇到 {e.seen} 次；附上 {e.uses} 次，有效 {e.wins}、無效 {e.fails}（{state}）\n- 建立：{e.at}\n\n"
                f"## 下次要注意\n\n{e.lesson}\n\n"
                "（可以直接修改上面這段；刪掉這個檔案就不再使用這筆經驗）\n\n"
                f"<!-- jiezi:{json.dumps(asdict(e), ensure_ascii=False)} -->\n")
        self._path(e.id).write_text(text, encoding="utf-8")

    # ── 用法 / use ──
    def record(self, question: str, error: str, step: str, lesson: str) -> Lesson:
        """寫一筆經驗；同一種題目已有就合併（次數加一、教訓換成新的）。 / Write or merge a lesson."""
        lesson = lesson.strip()[:LESSON_MAX]
        with self.lock:
            same = max(((e, similarity(question, e.question)) for e in self.load()), key=lambda x: x[1],
                       default=(None, 0.0))
            if same[0] is not None and same[1] >= SAME:
                e = same[0]
                e.seen += 1
                e.error, e.step = error[:300], step
                if lesson:
                    e.lesson = lesson
                if e.disabled is False and e.fails >= FAIL_LIMIT:
                    e.fails = 0           # 新的教訓重新給機會 / a new lesson gets a fresh start
            else:
                now = datetime.now().astimezone()
                e = Lesson(id=f"{now:%Y%m%d-%H%M%S}-{_slug(question)}", question=question[:300], error=error[:300],
                           step=step, lesson=lesson, at=now.isoformat(timespec="seconds"))
            self._write(e)
            return e

    def relevant(self, question: str, k: int = MAX_HINTS) -> list[Lesson]:
        scored = [(similarity(question, e.question), e) for e in self.load() if e.active and e.lesson]
        return [e for s, e in sorted(scored, key=lambda x: -x[0]) if s >= MATCH][:k]

    def outcome(self, ids: list[str], success: bool) -> None:
        """附上的經驗這次有沒有用。 / Whether the attached lessons helped this time."""
        if not ids:
            return
        with self.lock:
            for e in self.load():
                if e.id in ids:
                    e.uses += 1
                    if success:
                        e.wins += 1
                    else:
                        e.fails += 1
                    self._write(e)


def hint_text(lessons: list[Lesson]) -> str:
    lines = "\n".join(f"- {e.lesson}" for e in lessons)
    return ("[過去回答類似問題時的經驗——提醒，不是答案；以附上的資料與題目為準]\n" + lines)


LESSON_PROMPT = (
    "你剛剛回答一個問題，第一次沒答好，後來才解決。請用一到兩句繁體中文寫下「下次遇到類似問題要注意什麼」，"
    "寫成可以直接照做的提醒（例如：先查規則再推算、不要照不相關的資料回答、數字要用程式算的結果），"
    "並帶上最後答案裡最關鍵的一兩個事實。不要超過 120 字，只輸出提醒。\n\n"
    "問題：{question}\n第一次的問題：{error}\n最後怎麼解決：{step}\n最後的答案（節錄）：{answer}")
