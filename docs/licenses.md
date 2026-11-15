# 授權登記表 / License Registry

> 依規則 R18.3 建立：下載或使用任何模型、資料集、第三方資料前，先在此登記。
> Created per rule R18.3: register every model, dataset, or third-party data before downloading or using it.
> 程式以「登記鍵」引用本表；未登記者不得下載。標 ⚠️ 表示依據為二手資料（R19）。
> Code references this table by registry key; unregistered items are never downloaded. ⚠️ marks second-hand evidence (R19).
> 本專案第一版為研究 / 個人用途（R18.7）；標示「否」的項目不得用於商業用途。
> The first version is research / personal use (R18.7); items marked "no" must not be used commercially.

| 登記鍵 / Key | 項目 / Item | 來源 / Source | 授權 / License | 商用 / Commercial | 訓練 / Training | 查證日期 / Checked | 查證依據 / Evidence |
|---|---|---|---|---|---|---|---|
| `qwen3-0.6b-gguf` | Qwen3-0.6B GGUF（冒煙測試模型 / smoke model） | https://huggingface.co/Qwen/Qwen3-0.6B-GGUF | Apache-2.0 | 是 / yes | 是 / yes | 2026-11-14 | 鎖定 commit 的官方 `LICENSE` 檔 / official `LICENSE` at the pinned commit |
| `qwen3.5-gguf` | Qwen3.5 0.8B / 2B / 4B / 9B GGUF（E0 候選 / E0 candidates） | 檔案 / files: https://huggingface.co/unsloth （Qwen3.5-*-GGUF）；基底 / base: https://huggingface.co/Qwen （Qwen3.5-*） | Apache-2.0 | 是 / yes | 是 / yes | 2026-11-15 | Qwen 官方基底 repo 鎖定 commit 的 `LICENSE`，條款與標準 Apache-2.0 逐字相同；Qwen 官方沒有提供這些大小的 GGUF，檔案為 unsloth 轉檔（以 SHA-256 鎖定）/ official Qwen base `LICENSE` at the pinned commit, terms identical to canonical Apache-2.0; unsloth conversions pinned by SHA-256 |
| `ternary-bonsai-2` | Ternary-Bonsai-2 2B / 4B / 9B GGUF `Q2_0`（PrismML，Qwen3.5 三值化 / ternary Qwen3.5） | https://huggingface.co/prism-ml | Apache-2.0 | 是 / yes | 是 / yes | 2026-11-15 | 各 repo 鎖定 commit 的 `LICENSE`，條款與標準 Apache-2.0 逐字相同；基底 Qwen3.5 為 Apache-2.0 / each repo's `LICENSE` at the pinned commit, identical to canonical Apache-2.0; Qwen3.5 base is Apache-2.0 |
| `bonsai-1bit` | Bonsai-8B / Bonsai-27B GGUF `Q1_0`（PrismML，基底 Qwen3-8B / Qwen3.6-27B） | https://huggingface.co/prism-ml | Apache-2.0 | 是 / yes | 是 / yes | 2026-11-15 | repo 的 `LICENSE` / `LICENSE.txt`，條款與標準 Apache-2.0 逐字相同；Qwen3.6-27B 官方 `LICENSE` 亦同 / repo `LICENSE` / `LICENSE.txt` identical to canonical Apache-2.0; so is the official Qwen3.6-27B `LICENSE` |
| `bitcpm-cann` | BitCPM-CANN 3B / 8B GGUF `TQ2_0`（OpenBMB，MiniCPM4 三值 QAT / ternary QAT） | https://huggingface.co/openbmb | Apache-2.0 | 是 / yes | 是 / yes | 2026-11-15 | 模型卡指向 `OpenBMB/MiniCPM` 的 `LICENSE`（commit `f4293a1a`，標準 Apache-2.0）；該 README「Model LICENSE」段寫明模型為 Apache-2.0 / the model card points to the MiniCPM `LICENSE` (canonical Apache-2.0); the README's "Model LICENSE" section says the models are Apache-2.0 |
| `ceval` | C-Eval（val 分割 / val split） | https://github.com/hkust-nlp/ceval ；資料 / data: HF `ceval/ceval-exam` | 資料 CC BY-NC-SA 4.0；程式 MIT | 否 / no | 否（NC、SA 限制，未另行確認）/ no | 2026-11-14 | 官方 GitHub README「Licenses」段 / official README "Licenses" section |
| `cmmlu` | CMMLU | https://github.com/haonan-li/CMMLU ；資料 / data: HF `lmlmcat/cmmlu` | CC BY-NC-SA 4.0 | 否 / no | 否 / no | 2026-11-14 | 官方 GitHub README「许可证」段（HF 鏡像標 BY-NC，以官方為準）/ official README; the HF mirror says BY-NC, the official text wins |
| `chinese-simpleqa` | Chinese SimpleQA | https://huggingface.co/datasets/OpenStellarTeam/Chinese-SimpleQA | 資料 CC BY-NC-SA 4.0；評測程式 MIT | 否 / no | 否 / no | 2026-11-14 | 發布者官方資料卡 `license: cc-by-nc-sa-4.0`；GitHub README 說明評測程式為 MIT / publisher's dataset card; GitHub README states the eval code is MIT |
| `humanevalplus` | HumanEval+ | https://github.com/evalplus/humanevalplus_release （v0.1.10） | Apache-2.0（EvalPlus）；原始 HumanEval 為 MIT | 是 / yes | 是 / yes | 2026-11-14 | `evalplus/evalplus` 的 `LICENSE`；`openai/human-eval` 的 `LICENSE`（MIT） |
| `mbppplus` | MBPP+ | https://github.com/evalplus/mbppplus_release （v0.2.0） | Apache-2.0（EvalPlus）；原始 MBPP 為 CC BY 4.0 ⚠️ | 是（需姓名標示）/ yes (attribution) | 是 / yes | 2026-11-14 | `evalplus/evalplus` 的 `LICENSE`；原始 MBPP 授權取自 HF 資料卡 `google-research-datasets/mbpp`（`cc-by-4.0`）⚠️，官方 README 未載明 |
| `acebench` | ACEBench（`data_all/data_zh`） | https://github.com/chenchen0103/ACEBench | MIT ⚠️ | 是 / yes | 是 / yes | 2026-11-14 | repo 的 `LICENSE.md`（MIT）；⚠️ 該檔著作權行寫「Microsoft Corporation」，疑為範本未修改，授權類型仍為 MIT |
| `zh-wikipedia` | 中文維基百科典範條目 / zh Wikipedia featured articles | https://zh.wikipedia.org/ | CC BY-SA 4.0 | 是（需姓名標示、相同方式分享）/ yes (BY, SA) | 是（SA 限制衍生物）/ yes (SA applies) | 2026-11-14 | Wikimedia 使用條款（2023 起文字內容採 CC BY-SA 4.0）；報表與快取保留條目名稱與 revision 連結 / Wikimedia Terms of Use; reports keep title and revision link |
| `opencc-tscharacters` | OpenCC `TSCharacters.txt`（繁轉簡單字對照，供答案正規化）、`STCharacters.txt`（簡轉繁單字對照，供摘要「含簡體字」檢查，2026-11-15 加入）/ T→S table for answer normalization; S→T table for the summary simplified-character check (added 2026-11-15) | https://github.com/BYVoid/OpenCC （commit `fae2a0a911c30764e669a7d8b0591cd8e852934a`） | Apache-2.0 | 是 / yes | 不適用 / n/a | 2026-11-14 | 鎖定 commit 的 `LICENSE`；隨程式附上時保留授權聲明 / `LICENSE` at the pinned commit; license notice kept when bundled |
| `evalplus-code` | evalplus v0.3.1 判定邏輯（移植到 `src/jiezi/verify/code.py`）/ judging logic ported | https://github.com/evalplus/evalplus （tag v0.3.1，commit `e5d0ed0bab96280b60b637ec7f15b5e4841b0cb2`） | Apache-2.0；`evalplus/eval/__init__.py` 另有 MIT 檔頭（Copyright (c) OpenAI） | 是 / yes | 不適用 / n/a | 2026-11-15 | repo `LICENSE` 與檔頭；授權全文附於 `src/jiezi/verify/data/` / repo `LICENSE` and file header; texts bundled in `src/jiezi/verify/data/` |
| `acebench-code` | ACEBench normal 判定邏輯（移植到 `src/jiezi/verify/tool_call.py`）/ normal-category checker ported | https://github.com/chenchen0103/ACEBench （commit `56dd66cf6439b0d9655ee1b353e4cd745c6f664e`） | MIT（Copyright (c) Microsoft Corporation，見 `acebench` 列的 ⚠️）| 是 / yes | 不適用 / n/a | 2026-11-15 | repo `LICENSE.md`；全文附於 `src/jiezi/verify/data/ACEBench-LICENSE.md` |
| `chinese-simpleqa-grader` | Chinese SimpleQA 官方評審提示 `GRADER_TEMPLATE`（逐字沿用於 `src/jiezi/verify/judge.py`）/ official grader prompt reused verbatim | https://github.com/OpenStellarTeam/ChineseSimpleQA （commit `8b1aa9ebc5b91092356eb61f20f355c5993e6ce5`） | MIT（Copyright (c) 2024 OpenAI） | 是 / yes | 不適用 / n/a | 2026-11-15 | repo `LICENSE`；全文附於 `src/jiezi/verify/data/ChineseSimpleQA-LICENSE.txt` |
| `bubblewrap` | bubblewrap v0.13.1（程式驗證沙盒，建置到 `var/tools/`，不散布）/ code sandbox, built locally, not redistributed | https://github.com/containers/bubblewrap （commit `362936aea0d5c6e70f7af75d2d44b5a914cb4ba2`） | LGPL-2.1-or-later（0.12 起由 LGPL-2.0 改版 / since 0.12, from LGPL-2.0） | 是 / yes | 不適用 / n/a | 2026-11-15 | 鎖定 commit 的 `COPYING` 與 `NEWS.md` / `COPYING` and `NEWS.md` at the pinned commit |

## 已排除 / Excluded

| 項目 / Item | 原因 / Reason | 日期 / Date |
|---|---|---|
| CNewSum | 查不到資料授權：專案頁只標網站授權，資料放 Google Drive，內容為新聞平台文章；改用中文維基自建（使用者決定）/ No data license found; replaced by self-built Wikipedia items (user decision) | 2026-11-14 |
