# 異質推論執行環境（Hetero Runtime）設計計畫

> 遷入自 / Migrated from `LLM_discussion/plans/hetero-runtime.md`（2026-11-15，規則 R15 Q3：複製到 `docs/`，原處保留唯讀）。之後以本檔為準 / This copy is authoritative from now on.

> 需求：**(A) 大模型放得下 + (B) 更快 + (C) NPU 參與 + (D) 全部**
> 決策日期：2026-11-12
> 前置文件：[`hw-autoconfig.md`](hw-autoconfig.md)（硬體探測與參數決策）、[`../analysis/ggml-vs-onnxruntime.md`](../analysis/ggml-vs-onnxruntime.md)（第 13 章路線決策）

---

## 0. 一句話結論

**D 不需要寫「跨裝置排程器」，需要寫「多引擎編排 + 請求級路由」。**

理由：`ggml_backend_sched` 已處理單一行程內的裝置分配，但它**依序**執行、跨裝置要 copy（見 `hw-autoconfig.md` §6.5.2）；而 NPU 在 ggml 裡一次只能暴露一個裝置（`ggml-openvino.cpp:1127`）。所以「三個硬體同時參與」唯一可行的形式是**三個行程、三種資源、一個入口**。

---

## 1. 核心洞察：三個引擎剛好不搶同一種資源

| 引擎 | 主要資源 | 本機容量 | 競爭者 |
| --- | --- | --- | --- |
| llama.cpp + CUDA | VRAM | 6141 MiB | 無（只有它用 VRAM） |
| llama.cpp + OpenVINO(NPU) | 系統 RAM（NPU 無獨立記憶體） | 無 NPU | CPU 引擎 |
| llama.cpp + CPU | 系統 RAM | 16 GiB available | NPU 引擎 |

→ 真正的資源衝突只有一個：**NPU 與 CPU 引擎搶系統 RAM**。VRAM 引擎可獨佔。

這讓「同時在線」變成可行，而不是三個互斥。

---

## 2. 四個需求的落地方式（誠實版）

| 需求 | 手段 | 是否可行 | 備註 |
| --- | --- | --- | --- |
| **A. 大模型放得下** | `-fit on` + `-ngl` + `-ot`（llama.cpp 既有） | ✅ 現在就能 | fit 自動分層＋產生 `-ot`，會縮 context（用 `-fitc` 設下限） |
| **B. 更快** | ⚠️ **單 GPU 沒有 `-sm row`**，混用反而更慢 | 部分可行 | 真正的加速來源見 §3，不是「混用」 |
| **C. NPU 參與** | 獨立行程 + OpenVINO build + `GGML_OPENVINO_DEVICE=NPU` | ✅ 架構可行，本機無 NPU 無法驗證 | 只接**無狀態、固定 shape** 任務 |
| **D. 全部** | gateway + supervisor + policy（本文件） | ✅ | 工作量集中在編排層，不在 kernel |

---

## 3. 「更快」的真實來源（B 的拆解）

單張 RTX 4050 Laptop 上，**沒有任何混用手段能提高 tok/s**。可行手段全部是單裝置最佳化：

| 手段 | 旗標 | 預期效果 | 適用 |
| --- | --- | --- | --- |
| Speculative decoding | `--spec-draft-*`（含 `-hfd` 自動抓 draft 模型） | decode 1.5–2.5×（draft 命中率高時） | 需同家族小模型 |
| KV cache 量化 | `-ctk q8_0 -ctv q8_0` | 省 50% KV VRAM → 換更大 context 或更多層上 GPU | 幾乎無損 |
| Flash attention | `-fa on` | 長 context 下省 VRAM + 提速 | 長 context |
| 執行緒數 | `-t 14`（**實體核**，非 28） | CPU 路徑 +15~30% | 純 CPU / partial offload |
| micro-batch | `-ub` 調校 | prefill 提速 | 長 prompt |
| Prefix cache | `--cache-reuse N` + `--prompt-cache` | 重複系統提示時省大量 prefill | 多輪對話 / 固定 system prompt |
| 後端選擇 | CUDA vs Vulkan vs OpenVINO | CUDA 通常最快 | 需實測 |

> ⚠️ 反直覺但重要：**`-ngl` 開到上限不一定最快**。層在 CPU 上算雖然慢，但若換來更多層留在 GPU 且避免頻繁 copy，整體可能更快。這是 calibrator 存在的理由（§7）。

---

## 4. 系統架構

```
                        ┌──────────────────────────────────┐
   客戶端（OpenAI API）─▶│  gateway  :8000                  │
                        │  · 依 task class 路由             │
                        │  · 健康檢查 / 降級 / 重試         │
                        └───────┬──────────┬──────────┬────┘
                                │          │          │
              ┌─────────────────▼──┐  ┌────▼───────┐  ┌▼──────────────┐
              │ engine-chat        │  │ engine-    │  │ engine-cpu    │
              │ llama-server(CUDA) │  │ embed      │  │ llama-server  │
              │ :8080 router mode  │  │ (O V/NPU)  │  │ :8082         │
              │ 多模型 LRU          │  │ :8081      │  │ 備援/超量     │
              └────────────────────┘  └────────────┘  └───────────────┘
                     VRAM                 系統 RAM         系統 RAM
```

### 4.1 為什麼每個引擎是獨立行程（不共用一個 binary）

| 方案 | 可行性 | 結論 |
| --- | --- | --- |
| 單一行程，CUDA + OpenVINO 都編進去 | OpenVINO 只暴露一個裝置，且回報成 `GPU` → 與 CUDA 的 `GPU` 衝突；llama.cpp 有 GPU 時跳過 `IGPU` | ❌ 不可控 |
| 單一 binary + `GGML_BACKEND_DL` 動態載入 | 可行，但 OpenVINO 仍需 per-process env 選裝置 | ⚠️ 進階 |
| **不同 build、不同行程、不同 env** | 完全隔離，故障不互相污染 | ✅ **採用** |

### 4.2 三個 build

```bash
# build-cuda：聊天/生成
cmake -B build-cuda -DGGML_CUDA=ON -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release

# build-ov：embedding/rerank（在 Core Ultra 機器上才有 NPU 價值）
cmake -B build-ov -DGGML_OPENVINO=ON -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release

# build-cpu：備援（也可用 build-cuda 加 --device none 代替，省一顆 binary）
cmake -B build-cpu -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release
```

### 4.3 引擎啟動樣板

```bash
# 生成引擎（CUDA，router mode 管多模型）
llama-server \
  --models-dir ~/models/chat \
  --models-max 1 \
  --models-memory-margin 1024 \
  --models-autoload \
  --host 127.0.0.1 --port 8080 \
  -ngl 99 -fit on -fitp -fitc 4096 \
  -fa on -ctk q8_0 -ctv q8_0 \
  -t 14 --cache-reuse 256

# Embedding 引擎（NPU）
GGML_OPENVINO_DEVICE=NPU llama-server \
  --models-dir ~/models/embed --port 8081 \
  --embedding --pooling mean -c 512

# 備援引擎（CPU）
llama-server --models-dir ~/models/small --port 8082 -ngl 0 -t 14 -c 4096
```

> `--models-memory-margin` 是 router mode 的 LRU 卸載閾值（每裝置保留的 MiB），可避免新模型載入時 OOM。`--models-max 1` 在 6 GB VRAM 上是安全值。

---

## 5. 路由表（gateway 的唯一智力所在）

| 請求 | 目標引擎 | 理由 |
| --- | --- | --- |
| `POST /v1/chat/completions`（stream） | engine-chat | 需要 KV，只能單引擎完成 |
| `POST /v1/completions` | engine-chat | 同上 |
| `POST /v1/embeddings` | engine-embed | 無狀態、固定 shape → NPU 擅長 |
| `POST /v1/rerank` | engine-embed | 同上 |
| engine-chat 不可用 / OOM | engine-cpu | 降級 |
| engine-embed 不存在（本機無 NPU） | engine-chat 或 engine-cpu 的 `--embedding` | llama.cpp **支援 BERT 系架構**（`LLM_ARCH_BERT` / `JINA_BERT_V2` / `EUROBERT` / `GEMMA_EMBEDDING`），所以退化路徑完整 |

**鐵律**：
1. **一個生成請求不得跨引擎**——KV cache 無法交接，分離式 prefill/decode 不可行。
2. **路由單位是請求，不是 token，也不是層。**
3. 任何路由失敗 → 退回 engine-cpu → 仍失敗則回 503 並附 `reason`。

---

## 6. 元件清單與職責

| 元件 | 語言 | 職責 | 輸出 |
| --- | --- | --- | --- |
| `hwprobe` | Python（S1）→ C++（S2） | 探測 CPU/GPU/NPU/後端可用性 + 記憶體 | `facts.json` |
| `policy` | Python | facts + task class → 引擎選擇與參數 | `plan.json` |
| `supervisor` | Python | 依 plan 啟動/監控/重啟引擎；per-engine env | 行程 + 健康狀態 |
| `gateway` | Python（FastAPI） | OpenAI 相容入口 + 路由 + 降級 | HTTP |
| `calibrator` | Python | 跑 mini-bench 校正 ngl / draft / ubatch | `bench.json` |
| `watchdog` | Python | OOM 偵測、VRAM/RAM 水位、熱節流 | 事件 → policy 重算 |

> 除 `hwprobe` 的 C++ 版本外，全部用 Python。**不要一開始寫 C++ 編排層。**

---

## 7. 校準（calibrator）：唯一能回答「哪個比較快」的地方

`--fit` 是**靜態投影**，不是實測。所以「更快」必須靠校準：

```
for backend in [cuda, cpu]:
    for ngl in candidate_list(VRAM, model_size):
        for kv in [f16, q8_0]:
            run llama-bench -m model -ngl N -ctk kv -ctv kv -p 512 -n 128 -r 3
記錄 tok/s(pp) 與 tok/s(tg) → 取 Pareto 前緣
```

- 結果寫 `bench.json`，key = `(model_hash, backend, driver, ngl, kv, ctx)`
- gateway 啟動時查表；查不到才用 `--fit` 的保守值
- **快取失效條件**：模型檔 hash、GPU driver 版本、llama.cpp commit

候選 ngl 的產生方式：以 `--fit` 的結果為中心，上下各取 2–3 點（例如 fit 給 24 → 測 20/22/24/26/28/99）。

---

## 8. 記憶體與併發預算

```
VRAM 6141 MiB
  - CUDA context  overhead            ~300 MiB
  - 保留邊界（--models-memory-margin）1024 MiB
  → 可用於權重 + KV                    ~4800 MiB
  → 8B Q4_K_M（~4.9 GB）→ 需 partial offload 或更小量化
  → 4B Q4_K_M（~2.5 GB）+ ctx 8K(q8_0) → 舒適

RAM 16 GiB available
  - CPU 引擎：≤3B Q4_K_M（~2 GB）+ KV
  - NPU 引擎：與 CPU 引擎競爭 → supervisor 必須序列化載入
```

**併發規則**：
1. VRAM 引擎獨佔，不與他人共享。
2. RAM 引擎之間用 `models_max 1` + 全域鎖，避免同時載入。
3. 同時在線的引擎數 ≤ 2（本機）。

---

## 9. 分階段實作

### S1 — 唯讀探測（1–2 天，零風險）

- `hwprobe` 產出 `facts.json`：CPU 核數/ISA、GPU 名稱+VRAM、後端可用性（由 `--list-devices` 解析）、NPU 判定、記憶體水位
- 驗收：`facts.json` 與手動 `nvidia-smi` / `/proc/meminfo` 一致；NPU 欄位為 `none` 且附 `reason`

### S2 — 雙引擎 + gateway（3–5 天）

- `supervisor` 啟動 engine-chat(CUDA) + engine-cpu
- `gateway` 路由 chat / 降級
- 驗收：關掉 engine-chat → 請求自動落到 engine-cpu，客戶端無感（僅延遲上升）；`/healthz` 顯示各引擎狀態

### S3 — 校準與加速（3–5 天）

- `calibrator` 跑 ngl × KV 矩陣，寫 `bench.json`
- 加入 speculative decoding 實驗（同家族 draft 模型）
- 驗收：`bench.json` 中的最佳設定比 `--fit` 預設快 ≥10%（tg），否則記錄「預設已足夠」

### S4 — NPU 引擎（需 Core Ultra 機器）

- 第三個 build + `GGML_OPENVINO_DEVICE=NPU`
- 路由 embedding / rerank
- 驗收：NPU engine 的 embedding 吞吐 > CUDA engine × 0.5（否則沒有分流價值），且 VRAM 佔用為 0

> S4 在本機**無法驗證**（i7-14700HX 無 NPU）。請勿在此機器上假裝完成。

---

## 10. 風險與對策

| 風險 | 影響 | 對策 |
| --- | --- | --- |
| WSL2 VRAM 回報不準 | fit 誤判 → OOM | 取 `min(ggml_backend_dev_memory, nvidia-smi)`，並保留 1 GiB 邊界 |
| Router mode 同時載入多模型 | RAM 爆 | `--models-max 1` + 全域載入鎖 |
| OpenVINO NPU static shape | 只能固定 seq len | embedding 模型固定 `-c 512`，不做可變長 |
| `--fit` 偷縮 context | 使用者以為模型壞了 | `-fitc` 設下限 + `plan.json` 記錄實際 ctx |
| 三個 build 版本漂移 | 行為不一致 | 同一 git commit 建置三個 binary，`facts.json` 記錄 commit |
| 多引擎搶 port / 殘留行程 | 啟動失敗 | supervisor 用 pidfile + 啟動前掃 port |
| 「混用」被誤解為加速 | 期待落差 | 文件與 CLI 輸出一律標明「混用＝容量，不是速度」 |

---

## 11. 與 `hw-autoconfig.md` 的關係

- `hw-autoconfig.md` = **單一引擎內的參數決策**（fit、ngl、ot、profile）
- 本文件 = **多引擎之間的編排與路由**
- 兩者共用 `facts.json` 與 `bench.json`；`policy` 是唯一的決策點，輸出 `plan.json` 同時餵給兩層

```
facts.json ──▶ policy ──▶ plan.json ──┬─▶ supervisor（引擎/參數）
                                      └─▶ gateway（路由表）
bench.json ───────────────────────────┘
```

---

## 12. 未決事項（需要使用者拍板）

1. **專案位置**：建議 `~/projects/hetero-llm/` + `openspec init`
2. **S1 用 Python 還是 C++**：建議 Python（`subprocess` + `json`），S2 再視需要補 C++
3. **是否接受先裝 `cmake`**：`apt install cmake build-essential` 屬系統變更
4. **生成引擎是否啟用 router mode**：先單模型（簡單）或直接多模型 LRU（一次到位）
