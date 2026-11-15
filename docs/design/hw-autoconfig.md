# 硬體自動偵測與動態配置：設計計畫

> 遷入自 / Migrated from `LLM_discussion/plans/hw-autoconfig.md`（2026-11-15，規則 R15 Q3：複製到 `docs/`，原處保留唯讀）。之後以本檔為準 / This copy is authoritative from now on.

> 目標：自動偵測目前環境可用的 CPU / NPU / GPU，依各硬體擅長的工作動態選擇與預先設定，並在資源不足時優雅降級。
> 前置決策見 [`../analysis/ggml-vs-onnxruntime.md`](../analysis/ggml-vs-onnxruntime.md) 第 13 章（ggml 優先）。
> 狀態：**計畫，尚未實作。**

---

## 0. 一頁摘要

這件事的 70% 在 llama.cpp 裡已經有了，只是散落在不同工具與旗標中。本計畫的核心不是「從零寫一個 dispatcher」，而是：

1. **把既有的探測/適配能力整合成一個 deterministic 的決策管線**
2. **補上 llama.cpp 沒有做的 6 件事**（跨後端選擇、NPU 識別、用途 profile、校準快取、OOM 救援、決策可觀測性）

預估工作量：S1 薄殼 1–2 天、S2 精確探測 2–3 天、S3 校準 3–5 天。

---

## 1. 範圍與非目標

**範圍內**

- 單機、單一使用者、llama.cpp/ggml 生態
- 啟動時探測 → 產生可重現的執行設定
- 執行期 OOM 的自動降級
- 多用途 profile（chat / 長 prefill / embedding / draft）

**非目標（明確排除）**

- 執行中動態搬移權重（重建 context 成本過高，只當救援手段）
- 跨機器/分散式排程（那是 `ggml-rpc` 的領域）
- 非 ggml 的執行引擎（ORT 留到第 11 節的接縫）
- 自動量化決策（量化選型是資產管理問題，不是排程問題）

---

## 2. 先盤點：llama.cpp 已經有的（不要重造）

| 能力 | 既有機制 | 位置 | 備註 |
| --- | --- | --- | --- |
| 列舉裝置 | `--list-devices` | `common/arg.cpp` | 人可讀輸出，不適合程式解析（但可先擋著用） |
| 裝置屬性 API | `ggml_backend_dev_get_props()` | `include/ggml-backend.h` | 給 name / description / type / **memory_free / memory_total** / caps |
| 裝置類型 | `GGML_BACKEND_DEVICE_TYPE_{CPU,GPU,IGPU,ACCEL,META}` | 同上 | `ACCEL` 是加速器類，但 **NPU 不一定落在這裡**（見 8.1） |
| 記憶體查詢 | `ggml_backend_dev_memory()` | 同上 | free / total |
| 動態載入後端 | `GGML_BACKEND_DL` + `ggml-backend-dl.cpp` | CMake 選項 | 不必重編譯就能抽換 `.so` |
| 自動適配記憶體 | `llama_params_fit`（`-fit` / `-fitp` / `-fitt` / `-fitc`） | `common/fit.cpp` | **本計畫的主力**，說明見下 |
| 適配結果輸出 | `llama-fit-params` 二進位 | `tools/fit-params/` | 印出可餵給任何 llama.cpp binary 的 CLI 參數 |
| 逐張量放置 | `-ot pattern=BUFT` | `arg.cpp` | `fit` 會自動產生（例：`blk\.14\.ffn_(up|down|gate)_(ch|)exps=CPU`） |
| 裝置選擇/切分 | `-dev` / `-sm {none,layer,row,tensor}` / `-ts` | `arg.cpp` | |
| KV 放置 | `-nkvo` / `--no-kv-offload` | `arg.cpp` | |
| 執行期 op 回退 | `ggml_backend_sched` | `src/ggml-backend.cpp` | 免費：backend 不支援該 op 就丟回 CPU |
| 多模型記憶體管理 | `--models-memory-margin` | router server | LRU 卸載模型直到新模型放得下 |

### `llama_params_fit` 實際做了什麼（依 `tools/fit-params/README.md`）

- 投影模型在裝置上的記憶體用量，與**當下可用**裝置記憶體比較
- 不足時依序：**縮小 context**（`-fitc` 設下限）→ **分配層數** → **產生 `-ot` 把部分張量壓回 CPU**
- 保留 per-device 邊界（`-fitt`，預設 1024 MiB）
- 輸出即為 CLI 參數，可直接 `xargs llama-server`
- **限制**：只調整「未設定」的參數；`SPLIT_MODE_TENSOR` 未實作

→ 這意味著「預先設定」這一塊，多數情況只要正確呼叫它。

---

## 3. 真正要建的東西（6 項）

| # | 缺口 | 為什麼 llama.cpp 不處理 |
| --- | --- | --- |
| G1 | **跨後端選擇**（該用 CUDA / Vulkan / OpenVINO / CPU-only） | binary 編進去什麼就只能用什麼；`fit` 只看已註冊的裝置 |
| G2 | **NPU 識別與分流** | OpenVINO 把 NPU 報成 `IGPU`/`GPU`，型別欄位不可信 |
| G3 | **用途 profile** | `fit` 只保證「放得下」，不管「放得對不對」 |
| G4 | **校準快取** | `fit` 是靜態投影，不是實測 tok/s |
| G5 | **OOM 救援** | 沒有任何自動降級重試 |
| G6 | **決策可觀測性** | 沒有結構化的 facts / plan / reason 輸出 |

---

## 4. 架構：L0–L4

```
┌────────────────────────────────────────────────────────────┐
│ L4 calibrate   mini-bench → 二分搜尋最大可行 ngl → 快取      │
├────────────────────────────────────────────────────────────┤
│ L3 run         llama-fit-params → 啟動 → watchdog(OOM/節流) │
├────────────────────────────────────────────────────────────┤
│ L2 fit         呼叫 llama_params_fit（不自己算記憶體）       │
├────────────────────────────────────────────────────────────┤
│ L1 policy      facts + use_case + model_meta → plan         │
├────────────────────────────────────────────────────────────┤
│ L0 probe       ggml API → facts.json（結構化）              │
└────────────────────────────────────────────────────────────┘
```

**產物三件套**（缺一不可，否則無法除錯）

| 檔案 | 內容 | 用途 |
| --- | --- | --- |
| `facts.json` | 環境快照（硬體、後端、記憶體、driver） | 重現問題 |
| `plan.json` | 最終參數 + **每個參數的理由** | 解釋決策 |
| `bench.json` | 實測 tok/s、peak VRAM、是否 OOM | 校準回饋 |

---

## 5. L0 探測規格（`facts.json`）

```jsonc
{
  "schema": 1,
  "captured_at": "2026-11-12T16:00:00+08:00",
  "platform": {
    "kernel": "6.18.33.2-microsoft-standard-WSL2",
    "is_wsl": true,
    "has_nvidia_smi": true
  },
  "cpu": {
    "model": "Intel(R) Core(TM) i7-14700HX",
    "cores": 14, "threads": 28, "numa_nodes": 1,
    "isa": ["avx2", "avx_vnni", "fma", "f16c"],   // 注意：無 avx512 / amx
    "ram_total_mib": 31744, "ram_available_mib": 16384
  },
  "devices": [
    {
      "backend": "CUDA", "index": 0,
      "name": "NVIDIA GeForce RTX 4050 Laptop GPU",
      "ggml_type": "GPU",                 // GGML_BACKEND_DEVICE_TYPE_*
      "memory_total_mib": 6141, "memory_free_mib": 6141,
      "caps": { "async": true, "events": true, "host_buffer": true },
      "driver": "610.91",
      "note": "WSL2 回報的是 Windows 端總量，非獨佔可用量"
    },
    {
      "backend": "CPU", "index": 0, "name": "CPU",
      "ggml_type": "CPU", "memory_total_mib": null
    }
  ],
  "backends_compiled": ["CPU", "CUDA"],
  "missing_backends": ["Vulkan", "OpenVINO"]
}
```

**取得方式（優先序）**

1. **`ggml_backend_reg_count()` / `ggml_backend_dev_count()` / `ggml_backend_dev_get_props()`**（最精確，需自己編一個小工具）
2. `llama-cli --list-devices`（最快，靠 regex 解析）
3. OS 層補充：`nvidia-smi --query-gpu=...`、`lscpu`、`/proc/meminfo`、Vulkan ICD 目錄

**重要**：`backends_compiled` 只能在建置時決定，執行期無法補救。這代表「偵測」其實有一半是**建置矩陣問題**（見 S3）。

---

## 6. L1 決策：硬體擅長矩陣

| 工作負載 | 真正瓶頸 | 首選 | 次選 | 決策要點 |
| --- | --- | --- | --- | --- |
| **decode**（逐字生成） | 記憶體頻寬 | GPU | CPU | 第 9.2 節：`tok/s ≈ BW / (N×bpw/8)` |
| **prefill**（長 prompt） | 算力 / batch | GPU | CPU（多執行緒） | 需要 `-fa`、大 ubatch |
| **embedding / rerank** | 吞吐、小模型 | CPU（夠用） | — | offload 開銷可能大於收益 |
| **draft（投機解碼）** | 低延遲 | 與 target **同裝置** | — | 跨裝置搬移會吃掉收益 |
| **模型 > VRAM** | 容量 | CPU+GPU 混合 | 純 CPU | 交給 `-fit` 產生 `-ot` |
| **NPU** | — | （見 8.1） | — | ggml 只有 OpenVINO 一條路 |

**profile 定義（plan 的輸入，不是自動推論）**

| profile | 假設 | 傾向設定 |
| --- | --- | --- |
| `chat` | 短 prompt、長輸出 | 最大化 `-ngl`、KV 量化、`-fa on` |
| `bulk` | 長 prompt、短輸出 | 大 ubatch、可犧牲部分層給 CPU |
| `embed` | 無生成 | `-ngl 0` 或純 CPU |
| `draft` | 需與 target 共址 | 同 `-dev`、共用 KV 策略 |

### 6.5 異質執行（混用）——三種語意與硬限制

> 需求：「要能混用，不要只是純 CPU 或純 GPU 或純 NPU。」

#### 6.5.1 「混用」其實有三種完全不同的東西

| 語意 | 機制 | 是否平行 | 真正的用途 |
| --- | --- | --- | --- |
| **時間分層**（layer split） | `-ngl N`：前 N 層在 GPU、其餘在 CPU | **否**，序列交接 | 讓放不進單一裝置的模型能跑 |
| **張量覆寫**（per-tensor） | `-ot 'pattern=CPU'`（`fit` 會自動產生） | 否 | 把少數巨大張量（MoE experts）釘在 CPU，其餘留 GPU |
| **空間分割**（row split） | `-sm row` + `-ts N0,N1` | **是**（僅多 GPU） | 多 GPU 真正提速 |
| **張量平行** | `-sm tensor` | 是（實驗性） | 多 GPU；`llama_params_fit` **不支援** |
| **跨引擎分工** | 不同請求送不同 server | 是（行程級） | 讓 NPU 也參與（見 6.5.4） |

#### 6.5.2 關鍵事實：CPU+GPU 混用**不會更快**

`ggml_backend_sched` 把計算圖切成 subgraph，依 `supports_op` 分配給各 backend，**依序**執行，跨裝置處插入 copy。

```
GPU 算 layer 0..N  →  copy  →  CPU 算 layer N+1..  →  copy 回
```

所以：

- 吞吐上限 ≈ 最慢那一環 + 兩次傳輸延遲
- 混用解決的是**容量**，不是**速度**
- 「三個硬體一起算同一個 token」在 ggml 裡**不存在**（沒有 CPU+GPU 協同 kernel）
- 唯一真正平行的情況是多 GPU 的 `-sm row` / `-sm tensor`

實務含義：若模型放得進 GPU，**全放 GPU 永遠比混用快**。混用是「放不下時的降級方案」，不是「加速方案」。

#### 6.5.3 NPU **無法**與 GPU 在同一行程混用（原始碼證據）

`src/ggml-openvino/ggml-openvino.cpp:1127`：

```cpp
// Only the device selected by GGML_OPENVINO_DEVICE is offered for offload. The others are
// registered for discovery (--list-devices) only; llama.cpp skips IGPU devices when a GPU exists.
return ctx->ov_name == ggml_openvino_get_device_name() ? GGML_BACKEND_DEVICE_TYPE_GPU : GGML_BACKEND_DEVICE_TYPE_IGPU;
```

三個硬限制疊加：

1. **一次只暴露一個 OpenVINO 裝置**（由 `GGML_OPENVINO_DEVICE` 決定），其餘只註冊供列舉。
2. 被選中的回報成 `GPU`，其餘回報成 `IGPU`——而 llama.cpp **有 GPU 時會跳過 IGPU**。
3. NPU 走 **static shape** 路徑（README：「Static/NPU execution …」），LLM decode 是動態 shape；且原始碼註解直言「**NPU memory is too small even for kvcache**」。

→ **結論：`-dev CUDA0,NPU0` 這種組合目前不存在**。NPU 是「整檔切換」的層級（另一次啟動、另一個引擎），不是排程層級的裝置。

#### 6.5.4 可行的「三硬體參與」架構：工作分流，而非單模型混用

既然單一行程內做不到，就把「混用」提升到行程/服務層：

```
                    ┌─────────────┐
   請求 ──────────▶ │  dispatcher │  依任務類型分派（無狀態 vs 生成）
                    └──────┬──────┘
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   ┌────────────┐   ┌────────────┐   ┌────────────┐
   │ llama.cpp  │   │ OpenVINO / │   │  llama.cpp │
   │  CUDA      │   │ ORT on NPU │   │  CPU only  │
   │ 生成/對話   │   │ embedding  │   │ 超量/備援   │
   │            │   │ rerank/OCR │   │            │
   └────────────┘   └────────────┘   └────────────┘
```

| 任務類型 | 走哪個 | 理由 |
| --- | --- | --- |
| 生成（chat / 摘要 / 程式） | llama.cpp + CUDA | 頻寬受限，GPU 才有意義（第 9.2 節） |
| Embedding / rerank / 分類 | NPU（OpenVINO/ORT） | **無狀態**、固定 shape、低功耗 → 正是 NPU 擅長的 |
| 語音 VAD / OCR 前處理 | NPU | 同上 |
| 超量 / 備援 | CPU only | 永久安全網 |

**不可跨越的限制**：把「同一個生成請求」的 prefill 丟 NPU、decode 丟 GPU——**做不到**，因為 KV cache 無法在引擎間交接。所以 NPU 只能接「不需要 KV 的任務」。

#### 6.5.5 policy 決策規則（取代憑感覺）

```
1. if model_fits_single_gpu(profile)        → 全 GPU（最快）
2. elif model_fits(VRAM + RAM)              → layer split + -ot（fit 自動算）
3. elif model_fits(RAM)                     → 全 CPU
4. else                                     → 拒絕，並回報缺口
5. 若 task 無狀態且 NPU 可用               → 平行走 NPU 服務
6. 任何失敗                                 → 退回 (3)
```

> 規則 5 的完整落地（多引擎編排、路由表、supervisor、校準）見 [`hetero-runtime.md`](hetero-runtime.md)。
> 本文件負責**單一引擎內的參數決策**；該文件負責**多引擎之間的編排**。

---

## 7. 記憶體預算模型（給 policy 用的初值，最終仍交給 `fit`）

```
VRAM_need(n_offloaded) ≈
    Σ weights(layers[0..n_offloaded]) + output_layer
  + KV(n_ctx, n_offloaded, kv_type)          // 只在 KV 也 offload 時計入
  + compute_buffer(n_ubatch, n_batch)
  + backend_overhead                          // CUDA context + runtime
```

- `weights ≈ N_params × bpw / 8`（bpw 見分析文件第 9.1 節表）
- `KV = 2 × n_layer × n_kv_head × head_dim × n_ctx × bytes_per_elem`
- `backend_overhead`：WSL2 + CUDA 經驗值 **0.5–1.0 GiB**（**必須實測校準，勿寫死**）

原則：**policy 只給初值與上限，實際切割一律交給 `llama_params_fit`**。自己算記憶體是重造輪子，而且會與 upstream 行為漂移。

---

## 8. 缺口清單（你要求補充的部分）

### 8.1 NPU 在 ggml 裡「不是 NPU」

- `ggml-openvino` 明確支援 Intel NPU（`openvino/runtime/intel_npu/level_zero`、`NPU_DEVICE_ALLOC_MEM_SIZE`），但回報型別走的是 `GPU` / `IGPU`，**不是 `GGML_BACKEND_DEVICE_TYPE_ACCEL`**。
- 判定必須靠裝置名稱前綴（`NPU`、`GPU.N`）而非型別欄位。
- **本機沒有 NPU**：i7-14700HX（Raptor Lake）無 NPU，只有 RTX 4050。因此 NPU 偵測在本機永遠回 `none`——這是正確結果，不是 bug。
- 真正有 NPU 的場景：Intel Core Ultra（Meteor Lake+）→ 需 `GGML_OPENVINO=ON` + OpenVINO runtime。

### 8.2 WSL2 的記憶體回報不可全信

- `ggml_backend_dev_memory()` 在 WSL2 回報的是 **Windows 端 GPU 總量**，不反映其他 Windows 程式已佔用的部分。
- 對策：`facts.json` 同時記錄 `nvidia-smi` 的 `memory.used`，並在 policy 裡對 free 打折扣（建議取 `min(ggml_free, smi_free)`）。

### 8.3 `--fit` 只動「未設定」的參數

你手動指定了 `-c` 或 `-ngl`，fit 就不會碰它。所以 **policy 必須刻意留空**，不能好意先填。

### 8.4 `--fit` 會縮 context，這是意外行為

README 範例就出現 `context size reduced from 40960 to 4096`。要用 `-fitc` 設下限，並在 `plan.json` 記錄「context 被縮減」這件事——否則使用者會以為模型壞了。

### 8.5 `--fit` 是投影，不是實測

投影誤差來源：量化型別、`-fa`、KV 量化、backend overhead。必須用 mini-bench 校正，並把校正結果快取。

### 8.6 `--fit` 不支援 `-sm tensor`

若未來要用 tensor parallelism，適配邏輯要自己做（目前單機不需要，先標記）。

### 8.7 沒有跨行程的裝置鎖

兩個 `llama-server` 會互搶 VRAM 而互不知情。對策：用檔案鎖 + `facts.json` 的 free 值做 admission control；或改用 router server 的 `--models-memory-margin` 統一管理。

### 8.8 沒有熱節流 / 功耗感知

筆電長時間跑會降頻，tok/s 會漂。**不要**據此自動切換裝置（切換成本 >> 收益），只記錄並在 `bench.json` 標註。

### 8.9 量化型別 × 後端相容矩陣要自己維護

例如 `Q4_K` 在 CPU 有 repack 最佳化、CUDA 對某些 IQ 型別的 FlashAttention 支援不一。這張表要從 upstream 的 CI 與 `ggml-*` 的 `supports_op` 推導，並隨版本更新。

### 8.10 決策必須可重現

`plan.json` 的快取 key 建議：`hash(backend_build_id, gpu_name, driver, model_sha256, quant, n_ctx, profile, facts.available_mib_bucket)`。沒有 key 就會每次跑出不同結果，無法 A/B。

### 8.11 「建置矩陣」才是偵測的上限

執行期探測只能看見「已編進 binary 的後端」。要真正「依環境自動選擇」，必須先建好多後端產物（CPU / CUDA / Vulkan / OpenVINO），再用 `GGML_BACKEND_DL` 在執行期載入。**這是 S3 的主要工作，也是最容易被低估的一塊。**

### 8.12 安全網：純 CPU 必須永遠可行

任何探測失敗、後端載入失敗、OOM 連環失敗，最後都要能退回「純 CPU + 小 n_ctx」。這是整套系統的地板，不能有例外。

---

## 9. 分階段與驗收

### S1 — 薄殼（1–2 天）

- Python：解析 `--list-devices` + `nvidia-smi` + `/proc/meminfo` → `facts.json`
- 呼叫 `llama-fit-params` → 取得參數 → 產生 `plan.json`（含 reason 欄位）
- 啟動 `llama-server`，失敗則降級重試（最多 3 次）

**驗收**

- [ ] 在 7B Q4_K_M（約 4.4 GB）上自動產生可用 `-ngl`
- [ ] `plan.json` 每個參數都有非空 reason
- [ ] 同一份 `facts.json` 兩次執行產生 byte-identical `plan.json`

### S2 — 精確探測（2–3 天）

- 寫一個小 C/C++ 工具 `hwprobe`，直接呼叫 `ggml_backend_dev_get_props` 輸出 JSON
- 與 S1 的 regex 版本比對，確認一致性
- 加入 `caps`、backend build id

**驗收**

- [ ] `hwprobe` 輸出的 free/total 與 `nvidia-smi` 差異 < 5%
- [ ] 拔掉 GPU（`CUDA_VISIBLE_DEVICES=""`）仍能產出可執行 plan

### S3 — 多後端與校準（3–5 天）

- 建置矩陣：CPU / CUDA / Vulkan（可選 OpenVINO）
- mini-bench：固定 prompt + `n_predict`，二分搜尋最大可行 `-ngl`
- 快取 + `bench.json`

**驗收**

- [ ] 校準後預測 tok/s 與實測誤差 < 15%
- [ ] OOM 三次連續失敗能退回純 CPU 並成功啟動
- [ ] 切換後端不需重新編譯（DL 載入）

---

## 10. 風險與對策

| 風險 | 影響 | 對策 |
| --- | --- | --- |
| ggml 無 ABI 保證 | `hwprobe` 每次升級可能壞 | 優先用 CLI（`llama-fit-params`）當介面，C API 只做補充 |
| `llama_params_fit` 行為變動 | 決策漂移 | 鎖定 llama.cpp commit；升級時重跑校準 |
| WSL2 GPU 直通限制 | 效能低於原生 Windows | 文件標註基準線；必要時比較原生 Windows 版 |
| 6.1 GB VRAM 太小 | 7B 以上全量 offload 不可行 | 一律部分 offload；8B 以上預設走混合 |
| 使用者手動覆寫參數 | fit 失效 | policy 偵測到使用者已指定就跳過並記錄 |

---

## 11. 與 ORT 的接縫（呼應第 13 章）

本計畫刻意把「執行引擎」抽象在 `plan.json` 之後：

```
facts.json → policy → plan.json ─┬→ llama.cpp  (現在)
                                 └→ ORT GenAI  (未來，需 CUDA + packed 圖)
```

- `facts.json` 的裝置描述可以直接餵給 ORT 的 EP 選擇。
- NPU 是**唯一**會迫使你走向 ORT/OpenVINO 的場景——這是第 13 章「ggml 穩定後再轉」的實質觸發條件。
- 反之，只要沒有 NPU 需求，留在 llama.cpp 就是成本最低的路。

---

## 12. 本機 baseline（2026-11-12 實測）

| 項目 | 值 |
| --- | --- |
| 平台 | WSL2, kernel 6.18.33.2-microsoft-standard-WSL2 |
| CPU | i7-14700HX, 14C/28T, 1 NUMA node |
| ISA | AVX2 + AVX_VNNI + FMA + F16C（**無 AVX-512 / AMX**） |
| RAM | 31 GiB total, **16 GiB available** |
| GPU | RTX 4050 Laptop, **6141 MiB**, driver 610.91 |
| 已編後端 | 無（尚未建置） |
| `cmake` | **未安裝** ← P1 第一個阻塞 |
| `nvcc` | 未安裝（可裝 CUDA toolkit，不需 Windows 驅動） |
| Vulkan ICD | 缺 dzn / nvidia → Vulkan 後端暫不可用 |

**注意**：RAM 只剩 16 GiB 可用。這意味著即使純 CPU，也要把模型控制在 12 GiB 以內（含 KV 與 OS 餘裕），實務上約等於 **13B Q4_K_M（≈8 GB）為上限**。

---

## 下一步（需要你決定）

1. 專案落地位置：建議 `~/projects/<name>/`，並 `openspec init`（目前 `tmp/LLM_discussion` 只是研究目錄）
2. 先做 S1 薄殼，或先把 `cmake` 裝好做 P1（第 13 章）？
3. `hwprobe` 用 C++（精確）還是 Python（快）？
