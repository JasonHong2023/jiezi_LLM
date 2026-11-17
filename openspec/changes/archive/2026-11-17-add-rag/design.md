## Decisions

### D1 — 不用 numpy 的掃描 / Scanning without numpy
一開始用「全文候選（最多 200）＋向量重排」。2026-11-16 實測法規時發現與條文用語不同的問題（「酒駕會怎麼處罰」，條文寫「酒精濃度…駕駛」）連候選都撈不到，改為全掃描：記憶體只放截短到 256 維、重新正規化的向量（Qwen3-Embedding 支援 MRL），用 C 實作的 `math.sumprod` 掃描（4.7 萬條約 0.4 秒），前 50 名再用完整 1024 維重排，最後套門檻。
Full-text candidates missed differently worded questions; now 256-dim prefixes are fully scanned with math.sumprod and the top 50 reranked at full dimension.

### D2 — 兩個向量庫 / Two stores
知識庫段落（`var/knowledge/vectors.sqlite`，9,659 段）與現行法規條文（`var/laws/vectors.sqlite`，約 4 萬條）。法規只在問題沒有指名法律、但有法律用語時才用向量。
Knowledge sections and current statutes; statute vectors are used only for unnamed legal questions.

### D3 — 建置用 GPU / Build on the GPU
CPU 建向量約 4 秒一條（E0 同時佔用 CPU 時），4 萬條不可行；`--gpu` 在 E0 等評測沒在跑時建。查詢時的單句 embedding 在 CPU 上即可。
CPU embedding is too slow for the full build; `--gpu` builds when no evaluation runs. Query embedding stays on CPU.

### D4 — 實測 / Measurements
知識庫 5 段樣本：「台灣最高的山」→ 玉山 0.69、無關 ≤ 0.22。法規 94 條樣本：「酒駕會怎麼處罰」→ 刑法 185-3 條 0.69、道交條例 35 條 0.62；「肇事逃逸」→ 刑法 185-4 條 0.62；「撞到人要賠償嗎」→ 民法 191-2 條 0.61。門檻 0.5。
Samples: highest mountain → 玉山 0.69; drunk driving → Criminal Code 185-3 0.69; hit-and-run → 185-4; threshold 0.5.
