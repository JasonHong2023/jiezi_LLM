"""請教 Claude 時的參考網站提示（使用者 2026-11-15）。只提示 Claude 需要時可上網讀，芥子本身不收錄、不建索引、
不訓練——這些網站沒有開放授權，或以 robots.txt 禁止 AI 訓練爬蟲。
Reference-site hints for Claude consultations (user, 2026-11-15). Claude is only told it may read them online;
jiezi never ingests, indexes or trains on them — the sites are not openly licensed or forbid AI-training crawlers."""

from __future__ import annotations

import re

HINTS = [
    ("hackmd-chemistry",
     re.compile(r"化學|化合物|分子|原子|離子|莫耳|酸鹼|氧化|還原反應|週期表|元素|鍵結|有機物|溶液|濃度|反應式|"
                r"催化|電解|滴定|pH|(?<![A-Za-z])(?:[A-Z][a-z]?\d*)*[A-Z][a-z]?\d+(?:[A-Z][a-z]?\d*)*(?![A-Za-z0-9])"),  # 化學式要有數字 / formulas need a digit
     "這是化學相關問題。需要時可上網搜尋並閱讀 HackMD 化學主題的社群筆記作為參考"
     "（https://hackmd.io/community/topics/%E5%8C%96%E5%AD%B8）；筆記由個別作者撰寫、可能有錯，請交叉查證，"
     "用自己的話說明，不要大段照抄。"),
]


def hints_for(text: str) -> list[str]:
    return [hint for _key, cue, hint in HINTS if cue.search(text[:2000])]
