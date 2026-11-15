# 相關可用資料蒐集（2026-11-14）

> 遷入自 / Migrated from `LLM_discussion/analysis/related-resources.md`（2026-11-15，規則 R15 Q3：複製到 `docs/`，原處保留唯讀）。之後以本檔為準 / This copy is authoritative from now on.

> 依據：[`../plans/littlebit-selfevolve.md`](../design-principles.md) 的四條主線（極低位元核心、異質硬體、分層轉交、自我進化），以網路搜尋補充資料。
> **查證程度**：本文件的資料來自搜尋結果（論文摘要、官方頁面、二手整理），**沒有讀過全文**。標 ⚠️ 的數字只出現在二手來源，引用前必須先讀原文。
> 狀態：**只蒐集與評估，尚未納入計畫**（使用者指示先不要動手）。
> **更新（同日）**：§8 列出的 10 篇已讀完全文，見 [`deep-read-round3.md`](deep-read-round3.md)；其中的數字以該文件為準。特別修正：Qwen3-4B 三值的 37.35 t/s 已由原文證實（表 E），但原文未註明測試硬體；BitDistill 確認只做單一任務。

---

## 0. 最重要的五個發現

| # | 發現 | 對計畫的衝擊 |
| --- | --- | --- |
| 1 | **三值（1.58-bit）路線已有現成基礎建設**：llama.cpp 原生支援 `TQ1_0`（1.69 bpw）、`TQ2_0`（2.06 bpw）；微軟有 bitnet.cpp；BitDistill 能把現成 Qwen 0.6B–4B 微調成三值 | **E1 應加入第三組「三值 Qwen」**。它不必寫轉換器或新 kernel，L0/L1 的工作量可能大幅縮減 |
| 2 | **int4 會讓知識容量減半以上**（Physics of LM 3.3：int8 沒影響，int4 下降超過 2 倍；作者建議改在訓練時量化） | E1 的對照組 Qwen3-1.7B Q4_K_M 本身就已損失知識容量；**用 QAT 訓練的極低位元模型有理論上的翻身空間**。E1 應加一組 Q8 小模型 |
| 3 | **分層轉交已有成熟文獻**：RouteLLM（成本降超過 2 倍）、AutoMix（以小模型自我驗證決定是否轉交，成本降超過 50%） | 第 3 層的轉交門檻不用自己發明；RouteLLM 的 APGR / CPT 可直接當成本儀表板指標 |
| 4 | **CPU/GPU 真正協同運算已有實作**：Dovetail（draft 在 GPU、target 在 CPU）、PowerInfer（熱神經元在 GPU、冷的在 CPU）、KTransformers（MoE 熱專家在 GPU、冷的在 CPU，支援 AVX2） | 修正「單一請求無法加總裝置」的說法：**同一請求是有可能讓兩個裝置同時工作的**，只是需要特殊設計 |
| 5 | **小模型自我進化有成功案例**：rStar-Math 讓 7B 在 MATH 從 58.8% 到 90.0%，**沒有向大模型蒸餾**；但代價是 74.7 萬題、四輪、大量 MCTS 取樣，而且限定在數學 | 對 P1（雲端當老師）是重要反例；但條件是「可驗證領域 + 大量運算 + 7B 起跳」 |

---

## 1. 極低位元核心（LittleBit 的替代或補強）

| 資料 | 重點 | 可用性 | 來源 |
| --- | --- | --- | --- |
| **LittleBit-2**（ICML 2026，arXiv 2603.00042） | Internal Latent Rotation + Joint-ITQ，把 SVD 因子對齊到二值超立方體；推論零額外開銷；Llama-2/3 在 1–0.1 bpp 達 SOTA。⚠️ 二手報導：Llama-3 8B @ 1.0 bpp PPL 11.53 vs OneBit 13.09 | 官方 repo 以 `--use_itq` 提供；授權 CC BY-NC | [arXiv](https://arxiv.org/abs/2603.00042)、[PMLR](https://proceedings.mlr.press/v306/lee26y.html)、[Samsung Research](https://research.samsung.com/blog/LittleBit-2-Maximizing-the-Spectral-Energy-Gain-in-Sub-1-Bit-LLMs-via-Latent-Geometry-Alignment) |
| **BitNet b1.58 2B4T**（arXiv 2504.12285） | 從頭訓練的三值 2B 模型（4T tokens）；ARC-C 49.91、PIQA 77.09、WinoGrande 71.90、GSM8K 58.38；作者主張與同尺寸全精度模型相當（非超越） | **有 GGUF 可直接下載**（給 bitnet.cpp 用）；可當 E1 的現成參考點 | [技術報告](https://arxiv.org/pdf/2504.12285) |
| **bitnet.cpp**（arXiv 2410.16144、2502.11880） | x86 CPU 加速 2.37–6.17×（對比 llama.cpp FP16 基準）；聲稱無損。⚠️ 第三方提醒：100B 是合成設定的 kernel 測試，不是實測模型 | 開源；可在本機 CPU 測試 | [論文](https://arxiv.org/pdf/2410.16144)、[Bitnet.cpp edge](https://arxiv.org/html/2502.11880v1)、[第三方評論](https://wavect.io/blog/bitnet-cpu-llm-ram-requirements/) |
| **BitNet Distillation / BitDistill**（arXiv 2510.13998，微軟） | **把現成全精度模型（Qwen）微調成 1.58-bit**：SubLN + 持續預訓練暖身 + logits 與注意力蒸餾；記憶體省 10×、CPU 快 2.65×。⚠️ 偏向**特定下游任務**（二手稱含 GLUE 分類），未必是通用對話 | 程式碼在 `microsoft/BitNet`；**訓練成本可能遠低於 LittleBit 的 QAT** | [arXiv](https://arxiv.org/abs/2510.13998v1) |
| **llama.cpp `TQ1_0` / `TQ2_0`**（PR #8151） | AVX2 上 `TQ2_0` 是最快的量化格式；`TQ1_0` 略快於 Q4_K。**合併時只支援 CPU**。⚠️ bitnet.cpp 作者稱 llama.cpp 三值輸出與 FP32 不完全一致 | **本機已建好的 llama.cpp 就能跑**，不需要改程式 | [PR #8151](https://app.semanticdiff.com/gh/ggml-org/llama.cpp/pull/8151/overview) |
| **三值化推理模型的 PTQ**（arXiv 2608.01078、2609.16338） | ⚠️ 二手：Qwen3-4B 轉為 1.58-bit 後以 `TQ1_0` 在 CPU 跑 **37.35 t/s vs Q4_K_M 19.31 t/s**，檔案 1.01 GB | **最值得優先讀全文**：免訓練或低成本，且直接落在我們的工具鏈上 | [2608.01078](https://arxiv.org/pdf/2608.01078)、[2609.16338](https://arxiv.org/pdf/2609.16338) |

**[推論] 對 E1 的建議修訂**（尚未寫入計畫）

| 組別 | 模型 | 大小（估） | 特點 |
| --- | --- | --- | --- |
| A | Qwen3-8B LittleBit 0.55 + 詞表 K-quant | ~1.2 GB | 需雲端 QAT、需寫轉換器與計算圖 |
| B | Qwen3-1.7B Q4_K_M | 1.1 GB | 已在本機 |
| **C（新增）** | Qwen3-4B 三值（`TQ1_0`） | ~1.0 GB | **llama.cpp 已支援**；轉換成本依方法而定 |
| **D（新增）** | Qwen3-0.6B / 1.7B Q8_0 | 0.6–1.8 GB | 檢驗「int8 保留知識容量」的假說 |
| 參考 | BitNet b1.58 2B4T | 約 0.4–0.5 GB（未查證） | 現成、從頭訓練的三值模型 |

---

## 2. 知識容量的理論依據

| 資料 | 重點 | 來源 |
| --- | --- | --- |
| **Physics of Language Models 3.3**（Allen-Zhu & Li，ICLR 2025，arXiv 2404.05405） | 語言模型約可存 **2 bits 知識 / 參數**；**int8 幾乎沒影響，int4 下降超過 2 倍**（用 auto_gptq 做 PTQ），作者建議 int4 改在訓練時量化。⚠️ 二手整理稱 int4 約 0.7 bits/參數（原文未直接查到該數字）。結論來自合成資料的受控實驗 | [arXiv](https://arxiv.org/pdf/2404.05405)、[ICLR](https://proceedings.iclr.cc/paper_files/paper/2025/hash/26d3c9a66836ded8f34a944f2bfe868e-Abstract-Conference.html) |

**[推論]** 這修正了計畫 §1 第 2 點的算法。不能只比「儲存的位元數」，還要看「每個位元存多少知識」：PTQ 的 int4 效率約只有 int8 的一半；QAT 訓練的低位元模型則未知。這正是 E1 要量測的東西。

---

## 3. 分層轉交 / 路由

| 資料 | 重點 | 可用性 | 來源 |
| --- | --- | --- | --- |
| **RouteLLM**（ICLR 2025，arXiv 2406.18665，LMSYS） | 以偏好資料訓練路由器，在強弱模型間選一個；**成本降超過 2 倍且品質不變**；可泛化到訓練時沒見過的模型對；指標 **APGR**（彌補了多少品質差距）、**CPT**（要達到某品質需要多少比例轉交強模型） | 程式與資料開源（`lm-sys/RouteLLM`） | [arXiv](https://arxiv.org/pdf/2406.18665)、[ICLR](https://iclr.cc/virtual/2025/poster/30737) |
| **AutoMix**（NeurIPS 2024，arXiv 2310.12963） | **小模型先答 → few-shot 自我驗證 → POMDP 元驗證器決定是否轉交**；成本降超過 50%。注意：自我驗證有雜訊，所以才需要元驗證器 | 與我們第 0→3 層的設計幾乎相同 | [arXiv](https://arxiv.org/abs/2310.12963v5)、[NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2024/hash/ecda225cb187b40ea8edc1f46b03ffda-Abstract.html) |
| **FrugalGPT** | 以微調過的 DistilBERT 當閘門的模型串接（cascade） | 歷史參考 | 見 [路由與串接綜述](https://web.stanford.edu/~shuhuiq/blog/review-routing-cascades.html) |

**[推論]** 我們的設計是「驗證器優先」（V0），比 AutoMix 的自我驗證更可靠（9 篇論文的 P2）。RouteLLM 適合在**送出前**預判（省掉本機先跑一次的延遲）。兩者可以組合：先用路由器預判，本機回答後再交給驗證器把關。

---

## 4. 異質硬體：讓 CPU 和 GPU 同時做事

| 資料 | 分工方式 | 與本機的關係 | 來源 |
| --- | --- | --- | --- |
| **Dovetail**（EMNLP 2025，arXiv 2412.18934） | **draft 模型在 GPU、target 模型在 CPU**，target 平行驗證；傳輸粒度從區塊降到 token。v1：LLaMA2-7B 5.86 t/s、3 GB VRAM，比純 CPU 快 2.77×；v2：13B 快 1.79–10.1× | 論文動機正是「消費級裝置 GPU 弱、CPU 強」，**完全符合本機（4050 6 GB + 14700HX）** | [arXiv](https://arxiv.org/abs/2412.18934v2)、[ACL](https://preview.aclanthology.org/setup/2025.emnlp-main.879) |
| **DuoDecoding** | 反過來：draft 在 CPU、target 在 GPU | 適合模型放得進 VRAM 時 | 同上（Dovetail 文中提及） |
| **PowerInfer**（arXiv 2312.12456，上海交大） | 啟用次數呈冪律分布：**熱神經元放 GPU、冷的放 CPU**，兩邊各自計算，減少 PCIe 傳輸；RTX 4090 平均 13.2 t/s，比 llama.cpp 快最多 11.69× | 擴充自 llama.cpp；主要適用 ReLU 稀疏模型。⚠️ 維護狀態未查 | [arXiv](https://arxiv.org/html/2312.12456v2) |
| **KTransformers**（SOSP 2025，清華） | MoE：注意力與 KV 在 GPU、專家在 CPU；Expert Deferral 讓 CPU 使用率從 <75% 提高到近 100%；**2026-03 起支援純 AVX2 後端**；支援 LoRA 微調 | 本機 CPU 只有 AVX2（沒有 AMX/AVX-512），可用但吃不到 AMX 加速 | [論文](https://madsys.cs.tsinghua.edu.cn/publication/ktransformers-unleashing-the-full-potential-of-cpu/gpu-hybrid-inference-for-moe-models/)、[GitHub](https://github.com/kvcache-ai/ktransformers)、[PyPI](https://pypi.org/project/ktransformers/) |

**[推論] 修正先前的說法**：先前（hw-autoconfig §6.5.2、主計畫 §1 第 1 點）說「單一請求的解碼無法加總多個裝置」。那只對 **llama.cpp 的逐層分割** 成立。Dovetail（投機解碼）、PowerInfer（神經元分割）、KTransformers（專家分割）都能讓 CPU 與 GPU **在同一個請求中同時工作**。這是使用者「組合所有硬體一起運算」目標最直接的技術路線，值得在計畫中補上。

---

## 5. 自我進化：9 篇之後的新進展

| 資料 | 重點 | 對 P1–P8 的意義 | 來源 |
| --- | --- | --- | --- |
| **rStar-Math**（ICML 2025 oral，arXiv 2501.04519，微軟） | 7B 策略模型 + 7B 過程獎勵模型（PRM）+ MCTS；**不向大模型蒸餾**；四輪自我進化、74.7 萬題；MATH 58.8 → 90.0%、AIME 53.3% | **P1 的反例**，但條件嚴苛：可驗證領域（數學）、海量運算、7B 起跳 | [arXiv](https://arxiv.org/html/2501.04519v1)、[PMLR](https://proceedings.mlr.press/v267/guan25f.html) |
| **Darwin Gödel Machine**（ICLR 2026，arXiv 2505.22954，Sakana / Clune） | Gödel Agent 的實證版：不要求形式證明，改用基準測試驗證自我修改；維持 agent 檔案庫（開放式演化）；SWE-bench 20.0 → 50.0%、Polyglot 14.2 → 30.7%；沒有自我改進的版本停在 39% | 證明「檔案庫 + 實測驗證」能讓自我修改穩定；作者全程沙盒 + 人類監督（支持 P8） | [arXiv](https://arxiv.org/abs/2505.22954)、[Sakana](https://sakana.ai/dgm/) |
| **ExpeL**（arXiv 2308.10144） | 從經驗中歸納規則清單 + 檢索範例，放進 prompt；不更新權重 | 技能庫（V1）的文字版補充 | [arXiv](https://arxiv.org/html/2308.10144v3) |
| **Agent Workflow Memory**（ICML 2025，arXiv 2409.07429） | 從成功軌跡歸納出可重用的多步驟流程，存入記憶；⚠️ 跨任務 / 網站 / 領域勝過基準 8.9–14.0 分 | **V1 的直接參考**：工具呼叫流程的記憶化 | [ICML](https://icml.cc/virtual/2025/poster/45496) |
| **ExpGraph**（arXiv 2605.30712） | 與執行模型無關的經驗圖；指出「針對特定執行模型的訓練，在換模型時要重做」 | 支持「能力外置優先於權重更新」：核心模型從 LittleBit 換成三值時，技能庫不必重做 | [arXiv](https://arxiv.org/html/2605.30712) |

---

## 6. 本機可直接使用的元件

| 元件 | 用途 | 狀態 | 來源 |
| --- | --- | --- | --- |
| **Qwen3-Embedding-0.6B**（GGUF） | RAG 的向量化（R4） | 主線 llama.cpp 可用（`--embeddings --pooling last`）。⚠️ 中文 MTEB 分數未查 | [ggml / 社群 GGUF](https://huggingface.co/Mungert/Qwen3-Embedding-0.6B-GGUF) |
| **Qwen3-Reranker-0.6B**（GGUF） | RAG 的重新排序 | ⚠️ **支援度不穩**：部分轉換在 `/v1/rerank` 回傳接近 0 的分數；要用新版 llama.cpp 並實測相關文件分數是否較高 | [ggml-org Q8_0](https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF)、[修正版說明](https://huggingface.co/cicaba/Qwen3-Reranker-0.6B-GGUF-llamacpp-fixed) |
| **小模型工具呼叫的數據** | V0 / R0 工具呼叫題庫的基準 | ⚠️ ToolRM 論文：Qwen3-1.7B BFCL-v3 greedy 55.74、Qwen3-4B 62.45；**加上重排器（best-of-n）後 1.7B 再 +5.3**。另有社群報告指出 1.7B「敢呼叫工具，但不懂何時不該呼叫」 | [ToolRM](https://arxiv.org/pdf/2509.11963)、[Small Reasoning Models in FC](https://arxiv.org/pdf/2608.22472)、[TinyLLM](https://arxiv.org/html/2511.22138v1) |

**[推論]** ToolRM 的 best-of-n + 重排器，正是「N 條平行取樣 + 驗證器」用在工具呼叫上的實證：1.7B 可以提升約 5 分。

---

## 7. 蒸餾的服務條款（護欄 5.6-1）

| 供應商 | 條款（⚠️ 多為二手整理，需讀原文確認） |
| --- | --- |
| Anthropic | Usage Policy：未經事先授權，不得用輸入 / 輸出訓練 AI 模型（含 model distillation）；Commercial Terms 禁止訓練競爭模型 |
| OpenAI | 禁止用輸出開發與 OpenAI 競爭的模型 |
| xAI | 禁止用服務或輸出開發競爭模型 |
| DeepSeek（R1 模型授權） | 二手報導稱禁止用其輸出訓練競爭模型 |
| Mistral（Apache 2.0 開源模型） | 無此限制 |
| Google Gemini | **本次搜尋沒有查到** |

來源：[ConductAtlas – Anthropic](https://conductatlas.com/platform/anthropic/anthropic-api-usage-policy/prohibition-on-training-ai-models-using-outputs/)、[ConductAtlas – OpenAI](https://conductatlas.com/platform/openai/openai-terms-of-use/usage-policy-and-prohibited-conduct/)、[ConductAtlas – xAI](https://conductatlas.com/platform/xai/xai-terms-of-service/prohibition-on-competing-ai-development/)、[ConductAtlas – DeepSeek](https://conductatlas.com/platform/deepseek/deepseek-model-license/anti-distillation-clause/)、[Ertas 法律整理](https://www.ertas.ai/blog/ai-model-distillation-ip-law-2026)

**[推論]** 這是 V3（權重更新）的**實質阻礙**。主流商業 API 大多禁止或需要授權。可行的老師來源：(1) 本機或租用 GPU 跑的寬鬆授權開源大模型（Apache 2.0 / MIT 等）；(2) 取得供應商授權；(3) 只把商業 API 用在**推論期的轉交**與**不涉及訓練的技能庫 / 工作流程**（需確認條款是否涵蓋）。

---

## 8. 建議優先讀全文的清單（依對計畫的衝擊排序）

1. **2608.01078、2609.16338**（三值化推理模型、Qwen3-4B `TQ1_0`）：可能直接取代 L0/L1
2. **BitNet Distillation（2510.13998）**：確認是否適用於通用對話，以及實際訓練成本
3. **Dovetail（2412.18934）**：同一請求的 CPU/GPU 協同，本機條件幾乎相同
4. **Physics of LM 3.3 的量化章節**：查證 int4 的實際數字，並確認是否有 QAT 的結果
5. **AutoMix（2310.12963）+ RouteLLM（2406.18665）**：分層轉交的門檻設計與指標
6. **LittleBit-2（2603.00042）**：與 LittleBit-1 的差距、有沒有 Qwen3 的結果
7. **Agent Workflow Memory、ToolRM**：V0 / V1 的具體做法

---

## 9. 補充搜尋：落地資源（2026-11-14，第四輪）

> 目的：補齊「寫出可執行開發計畫」所缺的具體資源。多為模型頁面與二手整理，⚠️ 表示尚未讀原文或官方授權檔。

### 9.1 E0 可直接下載的極低位元模型
| 模型 | 格式 / 大小 | 本機可行性 | 重點 | 來源 |
| --- | --- | --- | --- | --- |
| **Ternary Bonsai 1.7B / 4B / 8B / 27B**（Prism ML） | GGUF `Q2_0`（主線 llama.cpp 可跑；**更正 2026-11-15：主線 `Q2_0` 是每 64 個一組，第一代預設的 g128 檔不適用，要用 `_g64` 檔；第二代 Ternary-Bonsai-2 的 `Q2_0` 檔官方註明主線 b11556 起可跑**）；`PQ2_0`/`PTQ1_0` 需 Prism fork；1.7B `PQ2_0` 約 442 MB | ✅ 本機 llama.cpp 有 `Q2_0`（CPU + CUDA 原始碼）**[本機查證]**；**2026-11-14 以 `test-backend-ops` 實測：`Q2_0` 的 CUDA 矩陣乘法 85/85 通過** | 第二代 Bonsai 2 的 2B/4B/9B 是**視覺語言模型**（附 mmproj）；Bonsai 2 27B：`PTQ1_0` 5.95 GB、`Q2_0` 7.63 GB（主線 b11556 起支援） | [1.7B](https://huggingface.co/prism-ml/Ternary-Bonsai-1.7B-gguf)、[4B](https://huggingface.co/prism-ml/Ternary-Bonsai-4B-gguf)、[8B](https://huggingface.co/prism-ml/Ternary-Bonsai-8B-gguf)、[27B](https://huggingface.co/prism-ml/Ternary-Bonsai-27B-gguf)、[Bonsai 2 27B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf)、[Bonsai 2 4B](https://huggingface.co/prism-ml/Ternary-Bonsai-2-4B-gguf) |
| **BitCPM-CANN 0.5B / 1B / 3B / 8B**（OpenBMB / 面壁 / 清華，2026-05） | GGUF `TQ2_0`（`llama-server -hf openbmb/BitCPM-CANN-8B-gguf:TQ2_0`）；另有可微調的未量化版本 | ⚠️ 本機有 `TQ2_0`，但**只能在 CPU 上做矩陣乘法**（見下方更正） | 中文團隊，**中文能力可能較佳**；⚠️ 二手：8B 全精度 81.31 → 三值 77.84（保留 95.7%） | [8B unquantized](https://huggingface.co/openbmb/BitCPM-CANN-8B-unquantized)、[3B](https://huggingface.co/openbmb/BitCPM-CANN-3B)、[IT之家](https://www.ithome.com/0/954/759.htm) |
| **Maple-Preview 20B-A1B**（DeepGrove） | 5.31 GB；**MIT 授權**；256 專家啟用 8 個；128K context；官方 GGUF 未見，僅社群轉檔 | ⚠️ 社群 GGUF（需實測） | ⚠️ 自稱 M4 Mac mini 218 t/s、IMO 級推理；**agent 能力幾乎沒有後訓練** | [Arx12 GGUF](https://huggingface.co/Arx12/Maple-Preview-Exact-GGUF)、[介紹](https://www.mindstudio.ai/blog/deepgrove-maple-preview-ternary-reasoning-model/) |

### 9.2 2-bit QAT
- **EfficientQAT**（arXiv 2407.11062，OpenGVLab）：先逐區塊訓練全部參數（Block-AP），再端到端只訓練量化參數（E2E-QP）。**單張 A100-80GB 約 41 小時就能做出 2-bit Llama-2-70B**，準確率差距小於 3%（69.48 vs 72.41）。⚠️ Qwen 結果與 llama.cpp 相容格式未查證。程式碼：`OpenGVLab/EfficientQAT`。[arXiv](https://arxiv.org/abs/2407.11062)

### 9.3 中文題庫（R0）
| 任務 | 候選 | 授權 / 備註 | 來源 |
| --- | --- | --- | --- |
| 工具呼叫 | **ACEBench**：中英平行、共 2000 筆、4538 個 API、8 大領域；分 Normal / Special（指令模糊或不完整）/ Agent（多輪）；**評分不需要 LLM** | 有 `data_zh` 中文版 | [arXiv](https://arxiv.org/abs/2501.12851v2)、[GitHub](https://github.com/ob1-s/ACEBench) |
| 中文問答（知識） | **Chinese SimpleQA**：3000 題、6 大主題 99 子題，短答事實題 | 資料 **CC BY-NC-SA 4.0**（禁止商用）；程式 MIT | [arXiv](https://arxiv.org/abs/2411.07140v2) |
| 中文問答（學科） | **CMMLU**（67 科）、**C-Eval** | 皆為 **CC BY-NC-SA 4.0** | [C-Eval](https://github.com/SJTU-LIT/ceval)、[CMMLU HF](https://huggingface.co/datasets/XiaHan19/cmmlu) |
| 文件摘要 | **CNewSum**：30.4 萬篇新聞，摘要高度抽象，測試集有「充分性 / 可推論性」人工標註；LCSTS（微博短文，240 萬組） | ⚠️ 資料授權未查 | [CNewSum](https://dqwang122.github.io/projects/CNewSum) |
| 程式 | HumanEval+ / MBPP+（語言中立）；可把題目描述翻成中文 | — | — |

→ 這些題庫都只能**內部評測**用；若產品要商用，對外宣傳分數前需確認授權。

### 9.4 老師階梯第 2、3 階的授權（⚠️ 二手整理）
| 模型 | 授權 | 能否用於蒸餾 |
| --- | --- | --- |
| **Qwen3 系列** | Apache 2.0 | 可 |
| **DeepSeek-R1**（含蒸餾版） | MIT（模型卡明文允許蒸餾）；蒸餾版另受底座模型授權約束 | 可 |
| **gpt-oss-20b / 120b** | Apache 2.0 | 可 |
| Maple-Preview | MIT | 可 |

來源：[SiliconFlow 比較](https://www.siliconflow.com/models/compare/deepseek-r1-distill-qwen-32b-vs-gpt-oss-120b)、[Interconnects](https://www.interconnects.ai/p/gpt-oss-openai-validates-the-open)、[Clarifai](https://clarifai.com/blog/top-10-open-source-reasoning-models-in-2026)

→ 修正 §7：先前二手資料說「DeepSeek 授權禁止蒸餾」，與「R1 為 MIT 且明文允許蒸餾」互相矛盾，**以官方授權檔為準**，使用前必須讀原文。

### 9.5 雲端 GPU 租金（2026-09～10，⚠️ 價格變動快）
| GPU | 價位 | 來源 |
| --- | --- | --- |
| H100 | 中位數約 US$3.25/小時；Lambda US$3.99–4.29；RunPod US$2.89–3.99 | [AIMultiple](https://aimultiple.com/gpu-index)、[Spheron](https://www.spheron.network/blog/h100-price-per-hour-2026/) |
| A100 80GB | 中位數約 US$1.76/小時；低價約 US$0.78–1.49 | [AIMultiple](https://aimultiple.com/gpu-index)、[Akash](https://akash.network/the-bid/h100-rental-price-2026-cost-per-hour/) |

**[自算] 主要訓練路線的雲端成本**
| 路線 | GPU 時數 | 費用（中位價） |
| --- | --- | --- |
| LittleBit QAT，Qwen3-8B @ 0.55 | 約 33 H100 小時（±2×） | 約 US$110 |
| ScaleQ 三值 PTQ，Qwen3-8B | 160 A100 小時 | 約 US$280 |
| ScaleQ 三值 PTQ，Qwen3-14B | 256 A100 小時 | 約 US$450 |
| EfficientQAT 2-bit，70B（Llama-2 數據） | 41 A100 小時 | 約 US$72 |
| BitDistill，0.6–4B（含 100 億 tokens 持續預訓練） | 未報告（推論：數百 GPU 小時） | — |


---

### 更正（2026-11-14，依專案規則 R19.4）

- **原說法**：「本機 llama.cpp 已有 `TQ1_0`/`TQ2_0`/`Q2_0`，CUDA 原始碼也有對應」（§9 與當日討論記錄）。
- **更正**：以 CUDA 建置後的 `test-backend-ops -o MUL_MAT -b CUDA0` 實測（llama.cpp commit `93cf736`）：**`TQ1_0` 與 `TQ2_0` 在 CUDA 上全部 `not supported`**，只有 `Q2_0` 支援（85/85 通過）。先前的判斷來自 grep 字串 `Q2_0`，它同時比對到 `TQ2_0`，屬於誤判。**[實測]**
- **影響**：
  1. Ternary Bonsai（`Q2_0`）可以在 GPU 上跑；BitCPM-CANN、BitNet 2B4T（`TQ2_0`/`TQ1_0`）在本版本中**矩陣乘法只能在 CPU 上執行**。
  2. ScaleQ-1.58 論文表 E 的「`TQ2_0` 在 GPU 320 t/s」，用本機版本**無法重現**（論文可能使用其他版本或 fork）。
  3. E0 必須把「三值格式在 GPU / CPU 上的支援度」列為比較條件之一，`TQ*` 格式的 GPU 數字不得與 `Q2_0` 直接比較。
