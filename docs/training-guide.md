# 如何訓練芥子（Jiezi）— 完整教學

> 版本：2026-11-16。適用 repo：`~/projects/jiezi_LLM`。
> 本文所有指令都在專案根目錄執行（`cd ~/projects/jiezi_LLM`）。
> 標示 **✅ 已實測** 的步驟在本機跑過；標示 **⚠️ 尚未實測** 的步驟程式已寫好、有單元測試，但還沒有用真正的 GPU 訓練跑過（要等 E0 選定核心模型、安裝 PyTorch 之後）。

---

## 目錄

1. [先搞懂：「訓練芥子」有五個層次](#1-先搞懂訓練芥子有五個層次)
2. [不能違反的規則](#2-不能違反的規則)
3. [層次一：在對話中直接教（記憶）](#3-層次一在對話中直接教記憶)
4. [層次二：加入新的知識來源](#4-層次二加入新的知識來源)
5. [層次三：建立語意向量（讓它「找得到」）](#5-層次三建立語意向量讓它找得到)
6. [層次四：量測它學得怎樣](#6-層次四量測它學得怎樣)
7. [層次五：改模型權重（LoRA 微調）](#7-層次五改模型權重lora-微調)
8. [換核心模型](#8-換核心模型)
9. [疑難排解](#9-疑難排解)
10. [指令速查表](#10-指令速查表)
11. [名詞解釋](#11-名詞解釋)

---

## 1. 先搞懂：「訓練芥子」有五個層次

很多人以為「訓練」就是改模型權重，但對一個 0.6B～4B 的小模型來說，**大部分的「學會」其實靠外掛的資料與記憶，而不是權重**。芥子的設計（開發計畫 §3、§5）把能力分成兩半：

- **模型權重**：負責「語言能力」——聽懂問題、組織句子、照格式回答、呼叫工具。
- **外掛資料**：負責「知識」——辭典、法規、課綱、台灣知識庫、記憶。回答時由 gateway 先查好，附給模型當依據。

所以「教芥子」由淺到深分成五個層次：

| 層次 | 做什麼 | 效果多快 | 會不會改權重 | 需要 GPU | 適合教什麼 |
|---|---|---|---|---|---|
| 一、記憶 | 對話中說「記住：…」「不對，…」 | 立刻 | 否 | 否 | 你的偏好、它答錯的事實 |
| 二、知識來源 | 加入新的資料集（辭典、法規…） | 建好就生效 | 否 | 否 | 大量可查的事實 |
| 三、語意向量 | 為資料建 embedding | 建好就生效 | 否 | 建置時建議用 | 讓「換個說法」也查得到 |
| 四、量測 | 自我評測、工具評測、缺口報告 | — | 否 | 跑評測時用 | 找出該教什麼 |
| 五、LoRA 微調 | 用驗證過的教材訓練權重 | 數小時 | **是** | **是** | 回答風格、格式、工具呼叫能力 |

**建議的順序**：先用層次一～三補知識，用層次四找出還有哪些弱點，只有「語言能力」上的弱點（例如格式老是錯、工具呼叫參數老是漏）才動用層次五。

> 為什麼不直接把知識訓練進權重？
> 1. 小模型容量有限，塞知識會擠掉語言能力（「災難性遺忘」）。
> 2. 外掛資料可以更新、可以附出處、可以被你檢查；權重裡的知識改不了、也看不到來源。
> 3. 換核心模型時，外掛資料原封不動就能沿用；權重訓練要重做。

---

## 2. 不能違反的規則

這些規則寫在 `reference/rules_20261114.md`，訓練相關的程式都會強制執行：

| 規則 | 內容 | 程式怎麼擋 |
|---|---|---|
| **R18.3** 授權先登記 | 任何資料、模型在下載前都要登記授權（`docs/licenses.md`），並標明「可不可以訓練」 | 每個資料清單（`*/manifest.toml`）缺授權欄位就拒絕建置 |
| **R20.3** 教材必須先過驗證器 | 只有驗證通過的內容才能當訓練教材 | `dataset export` 只收「強驗證」通過的回答 |
| **R20.2** 每輪從凍結核心開始 | 每一輪都從原始模型＋全新 LoRA 開始，不在上一輪上面疊 | `train sft` 拒絕重用已存在的 run 名稱 |
| **R20.1** 回歸關卡 | 目標任務要進步、其他任務退步 ≤ 1 分、回答長度增幅 < 20%、延遲不變差，不過關就回滾 | `train gate` |
| **R20.6** 獎勵駭客監控 | 靠「回答變長」或「更常轉交雲端」換來的分數不算進步 | `train gate` 檢查長度與轉交比例 |
| **評測不可污染** | 評測題（自我評測、R0 題庫、E0）絕不能進訓練資料 | `dataset export` 剔除評測題與評測「目標」 |
| **Claude 的輸出不可訓練** | Anthropic 使用條款限制用其輸出訓練模型 | 請教 Claude 的回答一律標 `training_use: false`，匯出時排除 |
| **禁止改作的資料不可訓練** | 教育部辭典是 CC BY-ND（禁止改作） | 用到辭典的對話一律排除 |

### 2.1 哪些資料可以訓練？

| 來源 | 授權 | 可訓練 | 備註 |
|---|---|---|---|
| 全國法規資料庫 | 政府資料開放授權條款第 1 版；法條不受著作權保護 | ✅ | |
| tw-taxonomy（國小課綱） | CC BY 4.0 | ✅ | 使用者 2026-11-15 決定含課綱條文 |
| zetria 課本章節 | MIT | ✅ | |
| Taiwan.md 台灣知識庫 | CC BY-SA 4.0 | ✅ | 衍生物適用「相同方式分享」；多數文章未經人工審核 |
| 本機模型自己答、且通過強驗證的回答 | Qwen（Apache-2.0）的輸出 | ✅ | 目前「強驗證」只有工具呼叫的 schema 檢查 |
| 教育部國語／台語／客語辭典 | CC BY-ND 3.0 TW | ❌ | 禁止改作，只能查詢 |
| Claude 的回答（含記憶 wiki 裡的） | Anthropic 條款 | ❌ | 只能查詢 |
| 故事革命、HackMD | 未開放授權 | ❌ | 只存連結 |
| 雲端模型的回答 | 依各家條款 | ❌（預設） | 要用前必須逐一確認條款並登記 |
| 評測題（ACEBench、C-Eval、CMMLU、SimpleQA…） | 多數禁止商用或為評測專用 | ❌ | 污染評測 |

---

## 3. 層次一：在對話中直接教（記憶）

**✅ 已實測**。最快、最直接的教法。記憶存在 `var/memory/wiki/`，是 Markdown 檔，格式和 Hermes llm-wiki 一樣，可以用 Obsidian 打開看、改、刪。

### 3.1 教它你的偏好：「記住」

在 `scripts/jiezi chat` 或任何連到芥子的客戶端說：

```
記住：我住新竹，回答盡量簡短，用條列。
```

芥子會回「好，我記住了」。之後**每一次對話**都會把這些記住的事附在系統提示裡。

- 存在：`var/memory/wiki/notes/使用者要我記住的事.md`
- 最多附最近 20 條、每條 300 字。
- 不要了就直接編輯或刪除那個檔案的條目。

### 3.2 糾正它答錯的事：「不對」

```
你：芥子是什麼植物的種子？
芥子：芥子是油菜的種子。
你：不對，是芥菜的種子
```

芥子會把「前一個問題＋你的更正」存成更正。之後問到**相似的問題**（相似度 ≥ 0.5），它會直接照你的更正回答，不再讓模型自己猜：

```
你：芥子是哪種植物的種子？
芥子：根據你 2026-11-15 的更正：是芥菜的種子
```

- 存在：`var/memory/wiki/topics/<主題>.md` 的「## 使用者更正」段。
- 更正的優先順序最高，高於辭典、知識庫和先前請教 Claude 的答案。

### 3.3 它請教過 Claude 的答案也會記住

本機答不出來而請教 Claude（或雲端）時，答案會自動存進記憶 wiki。下次問到幾乎一樣的問題（相似度 ≥ 0.85）會直接用記憶回答，不再花一次請教。

- 新聞、天氣、網址這類即時問題，以及問芥子自己的問題，**不會**存。
- 這些答案**只用來查，不會拿去訓練**（頁面標 `training_use: false`）。
- 180 天後不再使用（頁面保留，可以手動刪）。

### 3.4 管理記憶

```bash
scripts/jiezi memory list              # 列出所有主題與記住的事
scripts/jiezi memory search 芥子        # 查記憶裡跟某問題最像的答案與更正
scripts/jiezi memory forget 芥子_植物的種子   # 刪掉一整個主題
scripts/jiezi memory path              # 記憶 wiki 的位置
```

也可以直接用 Obsidian 開 `var/memory/wiki/`。改完不用重啟，下一題就生效（索引會自動重建）。

---

## 4. 層次二：加入新的知識來源

**✅ 已實測**（目前已有 7 個來源）。這是讓芥子「懂更多事」最有效的方法。

### 4.1 目前已有的來源

```bash
scripts/jiezi doctor        # 看每個來源有沒有建好
```

| 來源 | 指令 | 筆數 | 問什麼會觸發 |
|---|---|---|---|
| 教育部國語／台語／客語辭典 | `scripts/jiezi dict build` | 190,395 | 「X 是什麼意思」「台語的 X」「「X」的注音」 |
| 108 課綱知識圖譜＋國高中課本章節 | `scripts/jiezi curriculum build` | 569 主題、102 冊次 | 課綱代碼、國小學習、先修、課本單元 |
| Taiwan.md 台灣知識庫 | `scripts/jiezi knowledge build` | 9,659 段 | 台灣相關主題 |
| 全國法規資料庫 | `scripts/jiezi laws build` | 47,377 條 | 「民法第184條」「勞基法…」、法律用語 |
| 寫作教學連結 | `scripts/jiezi writing-refs build` | 131 篇（只存標題） | 寫作問題 |
| 計算、單位、日期、農曆 | （內建，不用建） | — | 算式、換算、日期、節日 |

一次全部重建（新電腦或資料損壞時）：

```bash
scripts/jiezi data build
```

### 4.2 加入一個新來源的完整流程

以「加入某個開放資料集」為例：

**步驟 1：確認授權（R18.3，最重要）**

- 找到資料的**官方授權頁**，確認：可不可以重製散布？要不要標示出處？可不可以改作（影響能不能訓練）？可不可以商用？
- 看 robots.txt：網站禁止爬蟲的話，只能用它正式公告的下載檔或 API。
- 寫進 `docs/licenses.md` 的授權表，註明查證日期與依據；依據是二手資料就加 ⚠️（R19）。

**步驟 2：鎖定版本**

下載一次，算 SHA-256，寫進清單。例如法規的 `laws/manifest.toml`：

```toml
[source]
key = "moj-laws"
title = "全國法規資料庫 中文法規_法律資料檔"
url = "https://sendlaw.moj.gov.tw/PublicData/GetFile.ashx?DType=XML&AuData=CF"
sha256 = "0c4f2685..."
size = 6065682
data_date = "2026-11-06"
license = "政府資料開放授權條款第 1 版（法律條文依著作權法第 9 條不受著作權保護）"
license_url = "https://data.gov.tw/dataset/18289"
training_use = true
attribution = "資料來源：法務部全國法規資料庫（…）"
license_checked = "2026-11-16"
```

`training_use` 決定這個來源能不能進訓練資料；**不確定就填 `false`**。

**步驟 3：寫建置與查詢模組**

參考現有的 `src/jiezi/laws.py` 或 `src/jiezi/dictionary.py`，至少要有：

- `build(root)`：下載（核對 SHA-256，不符就停）→ 解析 → 存 SQLite 到 `var/<名稱>/`。
- `grounding(obj, text)`：判斷問題要不要查這個來源，回傳「給模型的資料、來源清單、可不可訓練、附在回答後的原文」。
- 觸發條件要**寧缺勿濫**：無關的資料塞給小模型，它會被帶偏。

**步驟 4：接進 gateway**

在 `src/jiezi/runtime/gateway.py` 的 `_ground()` 加一段（照辭典、法規的寫法），在 `settings.py` 加開關（例如 `JIEZI_XXX`）。

**步驟 5：加進自我評測**

在 `src/jiezi/selftest.py` 加一個出題函式，標準答案直接取自資料本身。然後：

```bash
scripts/jiezi selftest --dry      # 不跑模型，看 gateway 附的資料有沒有包含答案
```

覆蓋率應該接近 100%；沒有的題目就是觸發條件或檢索有問題。

**步驟 6：重啟 gateway**

```bash
scripts/jiezi stop && scripts/jiezi start
curl -s 127.0.0.1:36100/health    # 新來源顯示 "on"
```

### 4.3 看它有沒有查到資料

每個查到資料的回答，最後都會附「---」之後的原文與出處，例如【法規原文】【辭典原文】【參考資料】【計算】【記憶】。沒有附就是沒查到。

---

## 5. 層次三：建立語意向量（讓它「找得到」）

**⚠️ 部分實測**（CPU 小樣本已驗證，完整建置排在 E0 結束後用 GPU）。

全文比對只能找到**字面相同**的內容。像「酒駕會怎麼處罰」，法條寫的是「酒精濃度…駕駛」，字面對不上。語意向量（Qwen3-Embedding-0.6B）能找到意思相近的段落。

```bash
scripts/jiezi knowledge embed --gpu   # 台灣知識庫 9,659 段
scripts/jiezi laws embed --gpu        # 現行法規約 4 萬條
scripts/jiezi stop && scripts/jiezi start
```

- 一定要在**沒有其他評測佔用 GPU 時**跑（`--gpu`）。CPU 也能跑但非常慢（約 4 秒一段）。
- 可以中斷後續跑（已建的會略過）。
- 門檻：相似度 ≥ 0.5 才採用（`.env` 的 `JIEZI_RAG_MIN`）。實測：「台灣最高的山」→ 玉山 0.69；無關問題 ≤ 0.22。
- 新增來源的資料改了之後，向量要重建（換了 embedding 模型會自動清空重建）。

---

## 6. 層次四：量測它學得怎樣

**✅ 已實測**（`--dry` 與報表）。「訓練」之前與之後都要量，否則不知道有沒有變好。

| 指令 | 量什麼 | 需要本機模型 |
|---|---|---|
| `scripts/jiezi selftest --dry` | gateway 附的資料有沒有包含答案（檢索上限） | 否 |
| `scripts/jiezi selftest` | 90 題（計算、單位、日期、注音、台羅、課綱、課本、知識庫、法規），只看模型自己寫的部分 | 是 |
| `scripts/jiezi toolcheck` | 50 題 ACEBench 工具呼叫，經過 gateway 的整套系統 | 是 |
| `scripts/jiezi gaps` | 實際對話中本機答不好的題目，分成資料缺口、觸發缺口、模型能力不足… | 否 |
| `scripts/jiezi dashboard` | 開發計畫 §1.3 的成功指標：達成率、本機處理率、速度 | 否 |
| `scripts/eval run …` | 標準評測（R0 題庫 300 題），用來比較模型與訓練前後 | 是 |

**用缺口報告決定該教什麼**：

| 缺口類型 | 意思 | 怎麼補 |
|---|---|---|
| 資料缺口 | 本機完全沒有相關資料 | 層次二：找新的來源 |
| 觸發缺口 | 有資料但沒查到 | 層次三，或調整觸發規則 |
| 有附資料仍答不好 | 資料給了，模型沒用好 | 層次五：這才是該訓練權重的情況 |
| 問芥子自己 | 「你是誰」之類 | 改系統提示 `src/jiezi/runtime/data/system_prompt.md` |
| 需要上網 | 天氣、新聞 | 本機做不到，交給 Claude（路由規則已處理） |

---

## 7. 層次五：改模型權重（LoRA 微調）

**⚠️ 尚未實測**。程式（`src/jiezi/train/`）與單元測試已完成；實際訓練要等：(1) E0 結束、G1 選定核心模型；(2) 你同意後安裝 PyTorch 等套件。

### 7.1 LoRA 是什麼？為什麼用它？

LoRA（Low-Rank Adaptation）不改原本的模型權重，而是在注意力與 MLP 層旁邊加一小組可訓練的矩陣（本專案預設 rank 16，約佔原模型 1% 以下的參數）。好處：

- 顯示記憶體需求小，6 GB 的筆電顯卡也能訓練 0.8B～2B 的模型。
- 訓練壞了只要丟掉 LoRA，原模型完全不受影響（R20.2）。
- 訓練完可以合併回原模型，再量化成 GGUF 給 llama.cpp 用。

### 7.2 整體流程

```
① 確認 G1 核心與硬體  →  ② 安裝套件並稽核  →  ③ 登記基底權重
        ↓
④ 匯出教材（dataset export）→  ⑤ 寫訓練設定  →  ⑥ 訓練（train sft）
        ↓
⑦ 合併並轉 GGUF（train export）→  ⑧ 評測（scripts/eval run + verify）
        ↓
⑨ 回歸關卡（train gate）── 不過 ──→ 回滾（丟掉這一輪）
        │
        過
        ↓
⑩ 部署（加進模型清單、JIEZI_CORE_MODEL）→ ⑪ 實際使用一段時間、看缺口報告 → 下一輪
```

### 7.3 ① 確認核心模型與硬體

```bash
scripts/eval e0 report        # E0 報表：各模型的知識、推理分數與速度
scripts/jiezi dashboard       # 達成率對照開發計畫目標
scripts/jiezi train plan      # 這台電腦的顯示記憶體能訓練哪些大小 [估]
```

`train plan` 在本機（RTX 4050 6 GB，預算約 5.1 GB）的估算：

| 模型大小 | bf16 LoRA | 4-bit（QLoRA） |
|---|---|---|
| 0.8B | ✅ 約 2.7 GB | ✅ 約 1.6 GB |
| 2B | ✅ 約 4.9 GB（很緊） | ✅ 約 2.2 GB |
| 4B | ❌ 約 8.8 GB | ✅ 約 3.2 GB |
| 9B | ❌ | ❌ 約 5.9 GB |

> 這是粗估（[估]），第一次訓練後以 `var/train/<run>/history.json` 記錄的實際峰值為準。訓練時 gateway 的本機模型要先停（見 7.8）。

### 7.4 ② 安裝訓練套件並做安全稽核

依使用者 2026-11-16 的決定，**E0 結束後**才安裝。版本以安裝當時的最新穩定版為準，安裝後一定要稽核（R23）：

```bash
# CUDA 版 PyTorch（版本與 CUDA 對應以 https://pytorch.org 當時的說明為準）
uv add torch --index https://download.pytorch.org/whl/cu128
uv add transformers peft
uv add bitsandbytes          # 只有 4-bit 訓練（2B 以上）才需要

scripts/jiezi audit          # 有「需處理」的漏洞就先停下來評估
```

確認可用：

```bash
uv run python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
```

### 7.5 ③ 登記基底權重（R18.3）

LoRA 要用 **Hugging Face 格式**的原始權重（safetensors），不是 GGUF。把 G1 選定的模型登記進 `docs/licenses.md`，並**鎖定 commit**：

```bash
# 例：查 Qwen3.5-0.8B 的最新 commit 與授權
curl -s https://huggingface.co/api/models/Qwen/Qwen3.5-0.8B | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['sha'], [t for t in d['tags'] if 'license' in t])"
```

把 commit 填進訓練設定的 `base_revision`。

### 7.6 ④ 匯出教材

**✅ 已實測**（2026-11-16 匯出 3,500 筆）。

```bash
scripts/jiezi dataset export              # 每個範本來源最多 2000 筆
scripts/jiezi dataset export --limit 500  # 想少一點
```

輸出：

- `var/training/sft-YYYY-MM-DD.jsonl`：一行一筆，OpenAI messages 格式，每筆帶 `source`、`license`、`training_use: true`、`sha256`。
- `var/training/sft-YYYY-MM-DD.manifest.json`：各來源筆數、授權、**各種排除原因的數量**。

**一定要人工抽查**：

```bash
python3 - <<'EOF'
import json, random
rows = [json.loads(x) for x in open("var/training/sft-2026-11-16.jsonl", encoding="utf-8")]
for r in random.sample(rows, 5):
    print(r["source"], "|", r["messages"][0]["content"][:60], "→", r["messages"][-1]["content"][:100], "\n")
EOF
cat var/training/sft-2026-11-16.manifest.json
```

檢查重點：答案對不對、有沒有簡體字、有沒有不該出現的來源、排除數量合不合理。

**教材從哪裡來**（`src/jiezi/training_data.py`）：

| 種類 | 內容 | 答案正確性 |
|---|---|---|
| 範本：法規 | 「民法第184條規定什麼？」→ 條文原文 | 原文，必然正確 |
| 範本：課綱 | 「國小數學的「X」要先學會什麼？」→ 先修主題 | 原文 |
| 範本：課本 | 「國中數學 7上 翰林版有哪些單元？」→ 單元表 | 原文 |
| 範本：Taiwan.md | 「請簡單介紹「九份」。」→ 文章開頭段 | 原文（但文章本身多未經人工審核） |
| 軌跡 | 本機自己答、而且工具呼叫通過 schema 驗證的回答 | 驗證過 |

**一定被排除的**：Claude 的回答、用到教育部辭典的對話、沒通過驗證或只有弱驗證（答案查核只看數字與引號，「刈包是四川菜」也會通過）、和評測題重疊（含同一冊課本、同一個課綱主題、同一條法條、同一篇文章）。

> **想要更多「能力」教材怎麼辦？** 正確做法是讓芥子在日常使用中累積「工具呼叫通過驗證」的軌跡（例如透過 Hermes、OpenCode 使用 jiezi 模型），而不是拿評測題或 Claude 的回答來充數。

### 7.7 ⑤ 寫訓練設定

存成 `var/train/configs/round1.json`（位置自訂）：

```json
{
  "base_model": "Qwen/Qwen3.5-0.8B",
  "base_revision": "<7.5 查到的 40 字元 commit>",
  "dataset": "var/training/sft-2026-11-16.jsonl",
  "run_name": "r1-qwen35-08b-20261117",
  "lora_r": 16,
  "lora_alpha": 32,
  "lora_dropout": 0.05,
  "learning_rate": 0.0002,
  "epochs": 2,
  "max_len": 2048,
  "batch_size": 1,
  "grad_accum": 16,
  "load_in_4bit": false,
  "gradient_checkpointing": true,
  "seed": 20261117
}
```

**參數怎麼調**：

| 參數 | 預設 | 意義 | 什麼時候改 |
|---|---|---|---|
| `lora_r` | 16 | LoRA 的容量 | 學不動就加到 32；過度擬合就降到 8 |
| `lora_alpha` | 32 | 縮放，通常是 r 的 2 倍 | 跟著 r 改 |
| `learning_rate` | 2e-4 | 學習率 | loss 不降就略升；loss 亂跳或回答變怪就降到 1e-4 |
| `epochs` | 2 | 資料看幾遍 | 資料少就 3；回答開始背範本句型就降到 1 |
| `max_len` | 2048 | 每筆最長 token | 顯示記憶體不足先降這個 |
| `grad_accum` | 16 | 累積幾筆才更新一次（等效批次 16） | 一般不用改 |
| `load_in_4bit` | false | QLoRA | 2B 以上依 `train plan` 決定 |

**教材配比的建議**：範本教材（法規、Taiwan.md）量大、句型單調，比例太高會讓回答變成「XX 規定：……」的固定格式。第一輪建議每種範本各取 300～500 筆（`--limit 500`），再看回歸關卡的長度與其他任務是否退步。

### 7.8 ⑥ 訓練

訓練會佔滿 GPU，先讓 gateway 的本機模型停下來（聊天會自動改由 Claude 回答）：

```bash
KEY=$(grep '^JIEZI_GATEWAY_KEY=' .env | cut -d= -f2)
curl -s -X POST 127.0.0.1:36100/admin/unload -H "Authorization: Bearer $KEY" \
     -H 'Content-Type: application/json' -d '{"hold_until":"2026-11-18T08:00","reason":"LoRA training"}'

scripts/jiezi train sft --config var/train/configs/round1.json
```

- 進度每 10 步印一次 loss 與顯示記憶體峰值。
- 產出 `var/train/<run_name>/`：`config.json`、`adapter/`（LoRA）、`history.json`（每步 loss、總秒數、峰值顯示記憶體）。
- **run 名稱不能重複**（R20.2）：每一輪都是全新的 LoRA。
- 訓練完解除暫停：同一個 curl，把 `hold_until` 改成 `null`。

**怎麼看 loss**：

- 正常：前幾十步快速下降，之後緩慢下降並趨平。
- 不降：學習率太低、資料格式有問題（看 `examples:` 的數量是否遠少於教材數，代表大量樣本被略過）。
- 降到接近 0：過度擬合，模型在背答案 → 減少 epochs 或教材量。

### 7.9 ⑦ 合併並轉成 GGUF

```bash
scripts/jiezi train export --run r1-qwen35-08b-20261117 --quant Q8_0
```

做三件事：用完整精度載入基底並合併 LoRA → 用鎖定版本的 `vendor/llama.cpp/convert_hf_to_gguf.py` 轉 f16 GGUF → 用 `llama-quantize` 量化。輸出 `var/train/<run>/<run>-Q8_0.gguf`，並印出 SHA-256 與大小。

量化格式建議與 E0 勝出的格式相同（例如 G1 選 Q4_K_M 就用 `--quant Q4_K_M`），這樣前後比較才公平。

### 7.10 ⑧ 評測訓練後的模型

用和訓練前**完全相同**的題庫、設定、評審：

```bash
scripts/eval run --backend local --model var/train/r1-qwen35-08b-20261117/r1-qwen35-08b-20261117-Q8_0.gguf \
     --ngl 99 --run-id r1-qwen35-08b-after --now
scripts/eval verify r1-qwen35-08b-after --now --judge-model nvidia-nemotron-3-ultra --judge-match nemotron
```

「訓練前」的對照就是 E0 裡同一個模型的評測目錄（例如 `var/eval/runs/e0-qwen3.5-0.8b-q8_0`）。另外也跑芥子整套系統的評測：

```bash
# 暫時把核心換成訓練後的模型（見第 8 節），再跑
scripts/jiezi selftest
scripts/jiezi toolcheck
```

### 7.11 ⑨ 回歸關卡

```bash
scripts/jiezi train gate \
     --before var/eval/runs/e0-qwen3.5-0.8b-q8_0 \
     --after  var/eval/runs/r1-qwen35-08b-after \
     --target tool
```

結束碼 0 = 通過，1 = 不通過。輸出範例：

```json
{
 "pass": false,
 "reasons": ["回答長度增加 ≥ 20%（70 → 92）"],
 "deltas": {"tool": 6.0, "code": -0.5, "qa": 0.0, "summary": -0.8}
}
```

**判準**（R20.1、R20.6）：

| 檢查 | 條件 |
|---|---|
| 目標任務 | 必須提升（`--target` 可以給多個） |
| 其他任務 | 退步不得超過 1 分 |
| 回答長度 | 平均回答 token 增幅必須 < 20% |
| 延遲 | 不得超過訓練前的 +5% |
| 轉交比例 | 不得上升超過 1 個百分點 |
| 缺分數 | 直接判不過（例如評審還沒跑完） |

**不通過 → 回滾**：什麼都不用做，這一輪的模型不部署就好；`var/train/<run>/` 留著當紀錄。連續兩輪無效就停止該方法（R20.1）；同一方法最多 3 輪後重新評估（R20.2）。

### 7.12 ⑩ 部署

1. 把 GGUF 移到 `models/`，在 `models/manifest.toml` 加一筆（`sha256`、`size` 用 export 印出的值；授權繼承基底模型）：

```toml
[[model]]
name = "jiezi-r1-qwen35-08b-q8_0"
file = "jiezi-r1-qwen35-08b-Q8_0.gguf"
url = "local://var/train/r1-qwen35-08b-20261117"
sha256 = "<export 印出的 SHA-256>"
size = <export 印出的大小>
license = "Apache-2.0"
license_url = "<基底模型的授權網址>"
commercial_use = true
training_use = true
license_checked = "2026-11-17"
source = "芥子第 1 輪 LoRA（基底 Qwen/Qwen3.5-0.8B @ <commit>；教材 sft-2026-11-16，3,500 筆）"
```

2. 在 `.env` 指定核心並重啟：

```bash
echo 'JIEZI_CORE_MODEL=jiezi-r1-qwen35-08b-q8_0' >> .env
scripts/jiezi stop && scripts/jiezi start
scripts/jiezi doctor
```

3. **隨時可回滾**：把 `.env` 的 `JIEZI_CORE_MODEL` 改回原模型名稱，重啟 gateway。

### 7.13 ⑪ 下一輪

1. 正常使用一段時間，讓軌跡累積。
2. `scripts/jiezi gaps` 看哪裡還不好。
3. 補資料（層次二、三）優先；真的是語言能力問題才再訓練。
4. 重新 `dataset export`（新的軌跡會進來）。
5. **新的 run 名稱**、**從原始基底開始**（不是從上一輪的 LoRA），重複 7.7～7.12。

---

## 8. 換核心模型

E0 會比較 18 個候選。G1 選出新核心後：

1. 確認模型已在 `models/manifest.toml`（E0 候選都已登記並下載在 `models/`）。
2. `.env` 加 `JIEZI_CORE_MODEL=<清單名稱>`，例如 `qwen3.5-2b-q4_k_m`。
3. 重啟 gateway：`scripts/jiezi stop && scripts/jiezi start`。
4. 跑 `scripts/jiezi selftest` 與 `scripts/jiezi toolcheck`，和舊核心比較。

外掛資料、記憶、向量都不用重建（它們和核心模型無關）。

---

## 9. 疑難排解

| 現象 | 原因 | 處理 |
|---|---|---|
| `training needs torch, transformers, peft` | 還沒安裝訓練套件 | 見 7.4 |
| `CUDA out of memory` | 顯示記憶體不足 | 先確認 gateway 已暫停本機模型（`/health` 的 engine 是 held）；降 `max_len`；改 `load_in_4bit: true` |
| `examples: N` 遠小於教材數 | 樣本太長或 chat template 前綴對不上被略過 | 提高 `max_len`；確認基底模型的 tokenizer 有 chat template |
| `… exists; every round needs a new run name` | run 名稱重複 | 換一個名稱（R20.2） |
| `… not marked trainable` | 教材裡混入不可訓練的資料 | 重新 `dataset export`，不要手動編輯 jsonl |
| `convert_hf_to_gguf failed` | 基底架構太新，鎖定的 llama.cpp 不支援 | 確認 E0 的 GGUF 能在鎖定版本執行；必要時討論升級 llama.cpp（R4） |
| 回歸關卡「缺少 X 的分數」 | 評審還沒跑完或中斷 | 重跑 `scripts/eval verify …` |
| 訓練後回答都變成「XX 規定：…」 | 範本教材比例太高 | 降 `--limit`、減 epochs |
| 訓練後簡體字變多 | 教材或基底的影響 | gateway 會把本機輸出轉繁體；檢查教材有無簡體字 |
| 「記住」沒效 | 句子沒以「記住」「請記得」開頭 | 開頭用「記住：」 |
| 某個問題沒查到資料 | 觸發條件沒命中 | `scripts/jiezi selftest --dry` 與 `scripts/jiezi gaps` 找原因 |

---

## 10. 指令速查表

```bash
# 記憶（層次一）
scripts/jiezi memory list | search <問題> | forget <主題> | path

# 知識來源（層次二）
scripts/jiezi data build                     # 全部重建
scripts/jiezi dict build|lookup <詞>
scripts/jiezi curriculum build|lookup|path|plan|textbook
scripts/jiezi knowledge build|search <問題>
scripts/jiezi laws build|lookup <問題>

# 語意向量（層次三）
scripts/jiezi knowledge embed --gpu
scripts/jiezi laws embed --gpu

# 量測（層次四）
scripts/jiezi selftest [--dry] [--list] [--policy jiezi-local]
scripts/jiezi toolcheck
scripts/jiezi gaps [--days 7]
scripts/jiezi dashboard
scripts/eval e0 report

# 微調（層次五）
scripts/jiezi train plan [--params 2]
scripts/jiezi dataset export [--limit 500]
scripts/jiezi train sft --config <設定.json>
scripts/jiezi train export --run <run_name> --quant Q8_0
scripts/jiezi train gate --before <目錄> --after <目錄> --target tool

# 維運
scripts/jiezi doctor | audit | start | stop | logs | status
```

---

## 11. 名詞解釋

| 名詞 | 說明 |
|---|---|
| 核心模型 | 芥子在本機跑的語言模型（目前 Qwen3-0.6B Q8_0；E0 後可能更換） |
| gateway | 芥子的中樞（`127.0.0.1:36100`），負責查資料、驗證、轉交、記錄 |
| grounding（附資料） | 回答前先查好資料，附給模型當依據 |
| 軌跡 | 每一次對話的完整紀錄（`var/trajectories/`），只存本機 |
| E0 | 18 個候選模型在同一份題庫上的比較，用來選核心（關卡 G1） |
| SFT | Supervised Fine-Tuning，用「問題→標準答案」訓練 |
| LoRA／QLoRA | 只訓練一小組附加矩陣的微調方法；QLoRA 把原模型以 4-bit 載入省顯示記憶體 |
| GGUF | llama.cpp 使用的模型檔格式 |
| 量化（Q8_0、Q4_K_M…） | 把權重壓成較少位元，換取更小、更快 |
| 回歸關卡 | 訓練後必須通過的檢查，確保沒有「顧此失彼」 |
| 強驗證／弱驗證 | 強：能證明答案正確（工具呼叫 schema）；弱：只能抓部分錯誤（答案查核、程式語法） |
| R18.3、R20… | 專案規則，見 `reference/rules_20261114.md` |
