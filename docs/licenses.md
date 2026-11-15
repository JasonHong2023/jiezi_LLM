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
| `ceval` | C-Eval（val 分割 / val split） | https://github.com/hkust-nlp/ceval ；資料 / data: HF `ceval/ceval-exam` | 資料 CC BY-NC-SA 4.0；程式 MIT | 否 / no | 否（NC、SA 限制，未另行確認）/ no | 2026-11-14 | 官方 GitHub README「Licenses」段 / official README "Licenses" section |
| `cmmlu` | CMMLU | https://github.com/haonan-li/CMMLU ；資料 / data: HF `lmlmcat/cmmlu` | CC BY-NC-SA 4.0 | 否 / no | 否 / no | 2026-11-14 | 官方 GitHub README「许可证」段（HF 鏡像標 BY-NC，以官方為準）/ official README; the HF mirror says BY-NC, the official text wins |
| `chinese-simpleqa` | Chinese SimpleQA | https://huggingface.co/datasets/OpenStellarTeam/Chinese-SimpleQA | 資料 CC BY-NC-SA 4.0；評測程式 MIT | 否 / no | 否 / no | 2026-11-14 | 發布者官方資料卡 `license: cc-by-nc-sa-4.0`；GitHub README 說明評測程式為 MIT / publisher's dataset card; GitHub README states the eval code is MIT |
| `humanevalplus` | HumanEval+ | https://github.com/evalplus/humanevalplus_release （v0.1.10） | Apache-2.0（EvalPlus）；原始 HumanEval 為 MIT | 是 / yes | 是 / yes | 2026-11-14 | `evalplus/evalplus` 的 `LICENSE`；`openai/human-eval` 的 `LICENSE`（MIT） |
| `mbppplus` | MBPP+ | https://github.com/evalplus/mbppplus_release （v0.2.0） | Apache-2.0（EvalPlus）；原始 MBPP 為 CC BY 4.0 ⚠️ | 是（需姓名標示）/ yes (attribution) | 是 / yes | 2026-11-14 | `evalplus/evalplus` 的 `LICENSE`；原始 MBPP 授權取自 HF 資料卡 `google-research-datasets/mbpp`（`cc-by-4.0`）⚠️，官方 README 未載明 |
| `acebench` | ACEBench（`data_all/data_zh`） | https://github.com/chenchen0103/ACEBench | MIT ⚠️ | 是 / yes | 是 / yes | 2026-11-14 | repo 的 `LICENSE.md`（MIT）；⚠️ 該檔著作權行寫「Microsoft Corporation」，疑為範本未修改，授權類型仍為 MIT |
| `zh-wikipedia` | 中文維基百科典範條目 / zh Wikipedia featured articles | https://zh.wikipedia.org/ | CC BY-SA 4.0 | 是（需姓名標示、相同方式分享）/ yes (BY, SA) | 是（SA 限制衍生物）/ yes (SA applies) | 2026-11-14 | Wikimedia 使用條款（2023 起文字內容採 CC BY-SA 4.0）；報表與快取保留條目名稱與 revision 連結 / Wikimedia Terms of Use; reports keep title and revision link |
| `opencc-tscharacters` | OpenCC `TSCharacters.txt`（繁轉簡單字對照，供答案正規化）、`STCharacters.txt`（簡轉繁單字對照，供摘要「含簡體字」檢查，2026-11-15 加入）/ T→S table for answer normalization; S→T table for the summary simplified-character check (added 2026-11-15) | https://github.com/BYVoid/OpenCC （commit `fae2a0a911c30764e669a7d8b0591cd8e852934a`） | Apache-2.0 | 是 / yes | 不適用 / n/a | 2026-11-14 | 鎖定 commit 的 `LICENSE`；隨程式附上時保留授權聲明 / `LICENSE` at the pinned commit; license notice kept when bundled |

## 已排除 / Excluded

| 項目 / Item | 原因 / Reason | 日期 / Date |
|---|---|---|
| CNewSum | 查不到資料授權：專案頁只標網站授權，資料放 Google Drive，內容為新聞平台文章；改用中文維基自建（使用者決定）/ No data license found; replaced by self-built Wikipedia items (user decision) | 2026-11-14 |
