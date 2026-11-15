# ggml vs ONNX Runtime — 原始碼級分析

> 遷入自 / Migrated from `LLM_discussion/analysis/ggml-vs-onnxruntime.md`（2026-11-15，規則 R15 Q3：複製到 `docs/`，原處保留唯讀）。之後以本檔為準 / This copy is authoritative from now on.

> 查證日期：2026-11-12
> 方法：以 `gh` API 直接讀取 repo metadata、release tag、目錄樹、CMakeLists、README、docs 與 `include/` 標頭，非憑記憶推測。
> 所有結構性敘述都可在對應路徑驗證。

---

## 0. 一句話定位

| | ggml | ONNX Runtime |
|---|---|---|
| 本質 | **張量庫（tensor library）+ 計算圖 + 後端排程器** | **模型格式執行引擎（inference/training runtime）** |
| 你要自己做的事 | 定義模型結構、forward 計算、權重載入 | 拿現成 `.onnx` 模型丟進去執行 |
| 類比 | 像「自己寫 PyTorch 的底層 CUDA kernel 層」 | 像「JVM 對 Java，但對象是 ONNX 模型」 |

這個差異是所有後續比較的根源：**ggml 是給你「建造」推論程式的積木，ORT 是給你「執行」既有模型的虛擬機器。**

---

## 1. 專案元資料（實測）

| 項目 | ggml | ONNX Runtime |
|---|---|---|
| Repo | [ggml-org/ggml](https://github.com/ggml-org/ggml) | [microsoft/onnxruntime](https://github.com/microsoft/onnxruntime) |
| 建立時間 | 2022-09-18 | 2018-11-10 |
| Star | 15,614 | 22,291 |
| Fork | 1,928 | 4,442 |
| 貢獻者（API 實測） | 441 | 403 |
| 授權 | MIT | MIT |
| 主語言 | C++（核心實作為 C） | C++ |
| 最新 release | `v0.29.0`（2026-11-04） | `v1.31.1`（2026-10-26） |
| main 分支版號 | 0.29.0 | `VERSION_NUMBER` = 1.33.0（開發中） |
| 目錄文件量 | `docs/` 僅 1 篇（`gguf.md`） | `docs/` 59 篇 |

值得注意：**ggml 的貢獻者數比 ORT 還多**（441 vs 403），但這是 llama.cpp 生態大量 PR 流動的結果，不代表 API 穩定度或治理成熟度。

---

## 2. ggml 架構剖析

### 2.1 檔案結構（`src/` 實測）

```
src/
├── ggml.c                 # 核心：張量、計算圖、算子實作
├── ggml.cpp               # 核心的 C++ 介面
├── ggml-alloc.c           # 記憶體配置器（arena / graph allocator）
├── ggml-quants.c          # 量化 / 反量化
├── gguf.cpp               # GGUF 模型格式讀寫
├── ggml-backend.cpp       # 後端抽象層
├── ggml-backend-reg.cpp   # 後端註冊表
├── ggml-backend-dl.cpp    # 後端「動態載入」(.so 插件)
├── ggml-backend-meta.cpp  # meta backend
├── ggml-opt.cpp           # 反向傳播 / 優化器（訓練）
├── ggml-threading.cpp
└── ggml-{cpu,cuda,metal,vulkan,sycl,hip,...}/   # 各硬體後端
```

### 2.2 五個核心抽象

1. **`ggml_context`** — 記憶體池。所有 tensor 都從這裡配置，整個 context 一次釋放。
2. **`ggml_tensor`** — 多維陣列 + metadata（type、shape、strides、`op`、`src[]` 來源）。它同時是「資料」也是「計算圖節點」。
3. **`ggml_cgraph`** — 有向無環計算圖。你建圖 → `ggml_build_forward_expand()` → `ggml_graph_compute()`。
4. **`ggml-alloc`（graph allocator）** — 分析整張圖的張量生命週期，做 **arena 式記憶體重用**。這是「執行期零配置」的關鍵。
5. **`ggml-backend` + scheduler** — 把圖切成多段，分派到不同裝置（例如 attention 在 GPU、某些 op fallback 到 CPU），並處理跨裝置 copy。

### 2.3 設計哲學（README 原文要點）

- Plain C/C++，**零外部依賴**
- 跨平台：x86、ARM、RISC-V、LoongArch、PowerPC、s390x、WebAssembly
- 手寫 SIMD kernel（x86 AVX/AVX512/AMX、ARM NEON/SVE、RISC-V RVV）
- **執行期零記憶體配置**（zero memory allocations during runtime）
- 量化：2–8 bit 整數 + **MXFP4 / NVFP4** 微縮放格式
- 後端橫跨 CPU / GPU / NPU / 瀏覽器

### 2.4 後端清單（`src/` 目錄 + CMake option 雙重驗證）

| 類別 | 後端 |
|---|---|
| CPU | `ggml-cpu`（含 `amx/`、`kleidiai/`、`llamafile/`、`spacemit/`、`repack`、`simd-gemm`） |
| NVIDIA | `ggml-cuda`、`ggml-musa`（摩爾線程） |
| AMD | `ggml-hip`（ROCm） |
| Apple | `ggml-metal` |
| 跨平台 GPU | `ggml-vulkan`、`ggml-opencl`、`ggml-webgpu` |
| Intel | `ggml-sycl`（oneDNN/Level-Zero 整合）、`ggml-openvino`、`ggml-zendnn`（ZenDNN） |
| NPU / 加速器 | `ggml-cann`（華為昇騰）、`ggml-zdnn`（IBM zDNN）、`ggml-hexagon`（Qualcomm）、`ggml-et` |
| 分散式 | `ggml-rpc`（把運算丟到遠端機器） |
| 虛擬化 | `ggml-virtgpu`（Virglrenderer API remoting） |
| 通用 | `ggml-blas`（BLAS / Accelerate） |

兩個容易被忽略的設計：

- **`GGML_BACKEND_DL`**：把後端編成獨立 `.so`，執行期動態載入 —— 與 ORT 的「plugin EP」思路相同。
- **`GGML_CPU_ALL_VARIANTS`**：一次編出多個 CPU 變體（不同 ISA），執行期挑最適合的。這是 CPU 端「一份二進位跑遍 x86」的解法，跟 ORT 的 MLAS 分派是同一問題的兩種答案。

### 2.5 量化格式（`include/ggml.h` 的 `enum ggml_type` 實測）

| 家族 | 型別 |
|---|---|
| 浮點 | `F32`、`F16`、`BF16`、`F64`、`F8_E4M3` |
| 傳統 block quant | `Q4_0`、`Q4_1`、`Q5_0`、`Q5_1`、`Q8_0`、`Q8_1` |
| K-quants | `Q2_K`、`Q3_K`、`Q4_K`、`Q5_K`、`Q6_K`、`Q8_K` |
| I-quants（importance matrix） | `IQ1_S`、`IQ1_M`、`IQ2_XXS`、`IQ2_XS`、`IQ2_S`、`IQ3_XXS`、`IQ3_S`、`IQ4_NL`、`IQ4_XS` |
| 三值 / 極低位元 | `TQ1_0`、`TQ2_0`、`Q1_0`、`Q2_0` |
| 微縮放（新） | `MXFP4`、`NVFP4` |
| SIMD 重排變體 | `Q4_0_4_4`、`Q4_0_4_8`、`Q4_0_8_8`、`IQ4_NL_4_4`、`IQ4_NL_4_8`、`IQ4_NL_8_8` |

重點洞察：**量化不是「額外工具」，而是型別系統的一部分。** 每個 quant type 都有自己的 GEMV/GEMM kernel 與 block 佈局，所以能榨出極致效能；代價是新增一種量化 = 要改所有後端。

### 2.6 GGUF 格式

`docs/gguf.md` 定義：單檔部署、`mmap` 友善、key-value metadata（可擴充）、包含載入所需全部資訊。是 GGML/GGMF/GGJT 的後繼者。
命名慣例：`[<Sidecar>]<BaseName><SizeLabel><FineTune><Version><Encoding><Type><Shard>.gguf`，其中 sidecar 已支援 `mmproj`（多模態投影器）與 `mtp`（多 token 預測頭）。

### 2.7 治理現實（關鍵）

README 明寫：

> For changes to the core `ggml` library (including to the CMake build system), please open a PR in **llama.cpp** — doing so will make your PR more visible, better tested, and better reviewed

且 commit log 中大量 `sync : llama.cpp`。意思是：**ggml 的真正開發主場在 llama.cpp，這個 repo 是同步鏡像。**
→ 對「想直接貢獻 ggml 的人」很不友善；也是它沒有獨立 roadmap、docs 幾乎空白的原因。

---

## 3. ONNX Runtime 架構剖析

### 3.1 檔案結構（實測）

```
onnxruntime/core/
├── graph/          # ONNX 圖 IR、GraphViewer、graph transformer 框架
├── optimizer/      # 171 個圖優化/融合規則
├── framework/      # session、記憶體規劃、EP 分派、data transfer
├── providers/      # 各 Execution Provider
├── mlas/           # 手寫線性代數 kernel 庫
├── quantization/   # 量化
├── session/        # InferenceSession
├── eager/          # eager 執行模式
├── flatbuffers/    # ORT format（.ort 序列化）
├── dlpack/         # DLPack 互通
└── util, common, platform, dll, mickey
```

### 3.2 執行管線（核心心智模型）

```
ONNX model (.onnx / .ort)
   │
   ├─ ORT format 載入 + 驗證
   ├─ Graph Resolve（型別推導、shape 推導）
   ├─ Graph Transformer 最佳化（constant folding、CSE、算子融合、layout 轉換）
   ├─ GraphPartitioner → 把子圖分派給各 Execution Provider
   ├─ 記憶體規劃（allocation_planner + BFC arena）
   └─ 逐節點執行（EP 提供 kernel，CPU fallback 保證正確性）
```

### 3.3 Execution Provider 清單（`onnxruntime/core/providers/` 實測）

`cpu`（MLAS）、`cuda`、`tensorrt`、`dml`（DirectML）、`openvino`、`qnn`（Qualcomm）、`nnapi`、`snpe`、`coreml`、`webgpu`、`webnn`、`migraphx`（AMD）、`dnnl`（oneDNN）、`xnnpack`、`cann`（華為）、`rknpu`（Rockchip）、`vitisai`（AMD/Xilinx）、`vsinpu`、`js`、`winml`、`azure`

**架構級變化：plugin EP。** repo 根目錄出現 `plugin-ep-cuda/` 與 `plugin-ep-webgpu/`，且 release 有獨立 tag（`plugin-ep-webgpu/v0.5.0`、`plugin-ep-cuda/0.3.0`）。代表 EP 從「編進 ORT core」轉向「**獨立發佈、執行期載入的插件**」——解決長年痛點：EP 碎片化 + 二進位肥大。

### 3.4 語言 / 平台綁定（根目錄實測）

`csharp/`、`java/`、`js/`（內含 `node/`、`web/`、`react_native/`）、`objectivec/`、`go/`、`rust/`、`winml/`、Python（`setup.py` + `pyproject.toml`）

→ 這是 ORT 對 ggml 最大的結構性優勢：**官方維護的多語言 API 與套件發佈（pip / NuGet / Maven / npm / CocoaPods）。**

### 3.5 圖優化器（171 個項目，抽樣）

`attention_fusion`、`bias_gelu_fusion`、`bias_skip_layer_norm_fusion`、`bias_softmax_fusion`、`cast_chain_elimination`、`cast_elimination`、`common_subexpression_elimination`、`constant_folding`、`constant_sharing`、`concat_slice_elimination`、`conv_activation_fusion`…

ORT 的效能很大一部分來自「把 PyTorch 匯出後破碎的算子圖重新融合回高效形式」。

### 3.6 MLAS（核心 CPU kernel 庫）

`amd64/`、`aarch64/`、`arm/`、`arm64ec/`、`amx_common.h`、`flashattn.cpp`、`flashattn_gqa.cpp`、`hqnbitgemm_kernel_*`（低於 4-bit 的 GEMV/GEMM）、`halfgemm`、`dgemm`、`convolve`…

→ ORT 有**自己的**手寫 kernel 庫（不依賴 oneDNN/OpenBLAS），這是它 CPU 效能的地基。

### 3.7 近期動向（main 前 10 commit，2026-11-12 抓取）

- `[CUDA] Optimize multi-token MatMulPacked GGUF GEMV (M=2..8)` — **ORT 正在最佳化 GGUF 權重格式的 GEMV**
- `[CUDA/CPU] Add hybrid GPU/CPU expert offload for MoEPacked block-packed weights` — MoE 專家卸載
- `WebGPU` profiling / trace viewer、`Attention` 卷積修正、JSEP 遷移計畫

**這是本次分析最重要的發現**：ORT 已經在吃 GGUF 格式與 LLM/MoE 專屬最佳化。兩者的領域邊界正在崩塌。

---

## 4. 架構維度對照

| 維度 | ggml | ONNX Runtime |
|---|---|---|
| **抽象層級** | 低階：張量 + 圖 + 後端排程 | 高階：模型容器 + EP 分派 + 圖優化 |
| **模型表示** | GGUF（自有二進位格式，為量化而生） | ONNX IR（產業標準，PyTorch/TF/sklearn 皆可匯出） |
| **誰做算子融合** | 你（在建模時就寫好） | 引擎（171 個 graph transformer 自動做） |
| **量化做法** | 型別層級：quant type 內建於張量系統，kernel 綁定 | 工具鏈層級：QDQ / 靜態 / 動態 / QAT，輸出標準 ONNX 算子 |
| **後端擴充** | 編譯期 CMake option；或 `GGML_BACKEND_DL` 動態載入 | 編譯期；新版轉向 plugin EP（獨立 repo/版本） |
| **跨裝置切圖** | backend scheduler 自動切 | GraphPartitioner + EP capability 宣告 |
| **記憶體** | arena / graph allocator，執行期零配置 | allocation_planner + BFC arena，可配置策略 |
| **訓練能力** | `ggml-opt`（反向傳播 + optimizer），輕量 | `orttraining/`（分散式、多節點 GPU、DeepSpeed 整合） |
| **除錯/剖析** | 幾乎無工具；靠 printf / 自建 | session profiling、ETW/Perfetto、ORT format、`ort.wprp` |
| **文件** | 1 篇 GGUF 規格 | 59 篇 + 官網教學 + roadmap |
| **治理** | 個人/小團隊主導，核心在 llama.cpp 開發後 sync | 微軟主導，CODEOWNERS、CoC、roadmap、telemetry |

---

## 5. 誠實檢視：各自最痛的地方

### ggml 的痛點
1. **API 不穩定、無 ABI 保證** — 每次 release 都可能 breaking；0.x 版號就是誠實宣告。
2. **文件近乎不存在** — `docs/` 只有 `gguf.md`，其餘靠讀 `ggml.h`（119 KB）與 llama.cpp 範例。
3. **算子集不完整** — 只有 LLM/影像推論需要的算子；想跑任意模型會缺 op。
4. **貢獻路徑反直覺** — 官方叫你去 llama.cpp 提 PR。
5. **沒有官方多語言 API** — `examples/python` 只是示範；Python 生態靠 `gguf`、`llama-cpp-python` 等第三方。
6. **沒有模型格式的型別系統** — GGUF 只管權重與 metadata，計算圖仍要你在程式碼裡寫死。

### ONNX Runtime 的痛點
1. **二進位巨大** — 完整套件數百 MB；雖有 custom build / 精簡工具，設定成本高。
2. **建置極複雜** — `build.py` + 大量 flag + 各平台工具鏈；自己編譯是地獄。
3. **EP 碎片化** — 每個 EP 的 opset 支援、bug、效能落差都不同；「支援但很慢」是常態。
4. **格式摩擦** — PyTorch → ONNX 匯出常失敗（動態 shape、自訂算子、控制流）。
5. **抽象稅** — 對純 LLM 推論，通用圖引擎的彈性反而成為額外開銷（這也是 llama.cpp 存在的原因）。
6. **telemetry 預設開啟** — 企業環境需注意。

---

## 6. 選型建議

| 你的情境 | 建議 | 理由 |
|---|---|---|
| 在邊緣裝置跑自己的 LLM，要極致記憶體效率 | **ggml**（實際上是走 llama.cpp） | block quant + arena + 零配置，無人能及 |
| 已經有 `.onnx` 模型（尤其非 LLM） | **ORT** | 唯一合理選擇 |
| 需要 Windows / DirectML / Windows ML 部署 | **ORT** | ggml 沒有對等產品 |
| 需要行動端（Android/iOS）官方支援 | **ORT**（或 llama.cpp 的 mobile 分支） | ORT 有完整的 NNAPI/CoreML/QNN + 官方套件 |
| 需要網頁部署 | 兩者都有（ggml-webgpu vs onnxruntime-web） | ORT 較成熟；ggml-webgpu 較新 |
| 需要 NPU（Qualcomm/昇騰/Rockchip） | **ORT** | EP 數量與廠商合作深度勝出 |
| 要研究/改造模型內部計算 | **ggml** | 你直接控制圖與 kernel |
| 企業級：SLA、多語言、可觀測性 | **ORT** | 治理、文件、profiling、支援體系 |
| 要訓練 | ORT（分散式）> ggml-opt（玩具級） | 成熟度差距明顯 |

### 一個容易忽略的判斷點

**如果你的模型是「少數幾種 transformer 架構」，ggml/llama.cpp 的效率優勢會壓倒一切；一旦你的模型種類變多、架構各異，ORT 的「通用性 + 圖優化」就會反超。** 這正是兩者長期共存的根本原因，而不是誰取代誰。

---

## 7. 趨勢判讀

1. **邊界正在模糊。** ORT 已加入 GGUF GEMV（CUDA）、MoEPacked expert offload；llama.cpp 生態則持續加 backend。兩者都在往對方領地移動。
2. **雙方都走向「後端插件化」。** ggml 的 `GGML_BACKEND_DL` ↔ ORT 的 plugin EP。共同原因：硬體碎片化太快，無法全部編進 core。
3. **低位元量化成為主戰場。** ggml 有 MXFP4/NVFP4/TQ/IQ 全家族；ORT 有 MLAS `hqnbitgemm` + QDQ 工具鏈。硬體（NVFP4/FP8）會決定下一輪勝負。
4. **MoE 是新的最佳化熱點。** 兩邊都在做 expert offload / block-packed 權重。
5. **llama.cpp 才是 ggml 的實質產品。** 評估 ggml 時，必須把 llama.cpp 一起看，否則會嚴重低估其工程成熟度（CI、測試、多平台建置都在那邊）。

---

## 8. 查證清單（可重現）

```bash
gh repo view ggml-org/ggml --json stargazerCount,forkCount,licenseInfo,createdAt
gh release list -R ggml-org/ggml -L 5
gh api repos/ggml-org/ggml/contents/src --jq '.[].name'
gh api repos/ggml-org/ggml/contents/CMakeLists.txt -H "Accept: application/vnd.github.raw" | grep -E "^option\("
gh api repos/ggml-org/ggml/contents/include/ggml.h -H "Accept: application/vnd.github.raw" | sed -n '/enum ggml_type {/,/};/p'
gh api repos/ggml-org/ggml/contents/README.md -H "Accept: application/vnd.github.raw"
gh api repos/ggml-org/ggml/contents/docs/gguf.md -H "Accept: application/vnd.github.raw"

gh repo view microsoft/onnxruntime --json stargazerCount,forkCount,licenseInfo,createdAt
gh release list -R microsoft/onnxruntime -L 5
gh api repos/microsoft/onnxruntime/contents/onnxruntime/core/providers --jq '.[].name'
gh api repos/microsoft/onnxruntime/contents/onnxruntime/core/optimizer --jq 'length'
gh api repos/microsoft/onnxruntime/contents/VERSION_NUMBER -H "Accept: application/vnd.github.raw"
gh api repos/microsoft/onnxruntime/contents/ --jq '.[].name'
```

---

## 9. 技術論點推導（不依賴實測）

> 本章的方法：把「快不快」拆解成**物理極限**與**實作稅**兩層，每層都用可驗證的原始碼事實支撐。目標是得出「不需要跑 benchmark 也能確定」的結論，並標明哪些必須靠實測才能定論。

### 9.1 第一性原理：LLM 推論有兩個完全不同的物理瓶頸

| 階段 | 每個 token 的工作 | 算術強度（FLOPs/byte） | 瓶頸 |
|---|---|---|---|
| **Prefill**（讀 prompt） | N 個 token 一起過權重 → GEMM | 高（隨 batch 線性成長） | **算力** |
| **Decode**（逐字生成） | 1 個 token 過權重 → GEMV | 極低（≈ 2 FLOP / 1 byte 權重） | **記憶體頻寬** |

Decode 的算術強度 ≈ 2 FLOPs/byte，遠低於任何現代 CPU/GPU 的 roofline 拐點（x86 約 10–50 FLOP/byte）。**結論：decode 階段，算力完全閒置，速度上限由「每秒能從記憶體搬多少權重」決定。**

推導 decode 的理論上限：

```
tok/s_max = BW_effective / bytes_per_weight_total
bytes_per_weight_total = N_params × bits_per_weight / 8
```

所以**位元寬直接、線性地決定速度上限**。這是理解 ggml 為何存在的唯一關鍵。

### 9.2 ggml 的量化佈局：由原始碼可精確推導

`src/ggml-common.h` 的每個 `static_assert` 都寫死了 block 大小，可直接算出精確位元寬（下表為推導值，非估計）：

| 型別 | bytes/block | elems/block | **bits/weight** | 7B 模型權重體積 |
|---|---:|---:|---:|---:|
| `TQ1_0` | 54 | 256 | **1.688** | 1.48 GB |
| `Q1_0` | 18 | 128 | **1.125** | 0.98 GB |
| `TQ2_0` | 66 | 256 | **2.062** | 1.80 GB |
| `Q2_0` | 18 | 64 | **2.250** | 1.97 GB |
| `MXFP4` | 17 | 32 | **4.250** | 3.72 GB |
| `Q4_0` | 18 | 32 | **4.500** | 3.94 GB |
| `Q4_K` | 144 | 256 | **4.500** | 3.94 GB |
| `Q5_0` | 22 | 32 | **5.500** | 4.81 GB |
| `Q6_K` | 210 | 256 | **6.562** | 5.74 GB |
| `Q8_0` | 34 | 32 | **8.500** | 7.44 GB |

（`Q4_0` 的 18 bytes = 2 bytes half scale + 16 bytes nibbles；`Q4_K` 的 144 = 4 bytes super-block scale + 12 bytes 子 block scales/mins + 128 bytes nibbles。）

**技術論點 1：ggml 量化開銷已接近理論下限。**
`Q4_0` 用 32 個權重共用一個 fp16 scale，額外成本 2/16 = 12.5% → 4 bit 變 4.5 bit。想再逼近 4.0 bit 就得加大 block（`Q4_K` 用 256 個權重含子 block → 仍是 4.5），或改用微縮放格式（`MXFP4` 4.25）。**這代表在「4-bit 級別」這個生態最常用的檔位上，幾乎沒有再壓縮的空間了。**

**技術論點 2：`Q4_0` 與 `Q4_K` 位元寬相同（4.5）但速度不同。**
`Q4_0` 的 scale 粒徑是 32，`Q4_K` 是「256 超塊 + 32 子塊」分層。同樣位元寬下，`Q4_K` 讀取時要多做一次 scale 解包與組合 → **單執行緒 decode 通常 `Q4_0` 更快，品質 `Q4_K` 更好**。這是「同一位元寬下，佈局決定速度」的直接證據。

### 9.3 同一位元寬下的三個決勝點

即使兩邊都是 4-bit，實際速度仍取決於三件事：

**(a) kernel 是否為該佈局「手寫」**

ggml 的每個 quant type 都有專屬 GEMV/GEMM（`src/ggml-cpu/quants.c`、`vec.cpp`、`simd-gemm.h`、`repack.cpp`）。
→ 讀 4-bit nibble 時直接 `_mm256_shuffle_epi8` 展開、用 `maddubs` 做點積，不必先解壓成 fp32 陣列。**反量化與乘加融合在同一組 SIMD 指令內** → 沒有中間 buffer，也就沒有額外頻寬損耗。

ORT 的 int4 走 `MatMulNBits` 算子（QDQ 圖重寫的產物），kernel 由各 EP 各自實作；CPU 端在 MLAS（`hqnbitgemm_kernel_*`）、CUDA 端在 `cuda` EP。
→ 設計目標相同，但**是否支援取決於 EP**。

**(b) 有沒有「格式轉換稅」**

- ggml：GGUF 檔案的二進位佈局 = 記憶體佈局 = kernel 讀取的佈局。`mmap` 後指標直接餵給 kernel，**轉換成本為零**；也因為 `mmap`，多個 process 共享同一份 page cache，載入幾乎瞬間完成。
- ORT：ONNX initializer 是 protobuf/flatbuffer 序列化的張量，載入後可能需 **transpose / pack 成 EP 偏好的佈局**（例如 MatMulNBits 的 block 打包）。這是一次性成本，但影響冷啟動；且每個 EP 的偏好佈局不同 → 同一模型換 EP 可能要重新打包。

**技術論點 3：ggml 把「檔案格式」與「kernel 佈局」綁死，換來零轉換稅；ORT 把兩者解耦，換來跨 EP 彈性但付出打包成本。** 這是典型的「耦合換效能」取捨。

**(c) dispatch 開銷**

- ggml：`ggml_backend_sched_graph_compute()` 對每個切分好的子圖**只呼叫一次** `backend->graph_compute()`，之後在 backend 內部跑一個節點迴圈（`src/ggml-backend.cpp:2372`）。張量指標在 `ggml_backend_sched_alloc_graph()` 時一次性配置（gallocr 算好靜態偏移）。
- ORT：`InferenceSession::Run()` 逐節點執行，每個節點經 `OpKernel::Compute()`，跨 EP 還要經 `DataTransferManager` 複製。雖然有執行計畫快取，但**每個 kernel 呼叫的固定成本**（status 檢查、input/output 指標解析、arena 配置查詢）在 batch=1 時占比不低。

Decode 每一步要跑數百個節點 → 若每個節點 1–5 µs 固定開銷，乘上數百個節點就是毫秒級，對「單步延遲敏感的 agent 迴圈」有感。**這是 ORT 在純 LLM 場景的結構性不利點。**

### 9.4 契約強度：硬性 vs 軟性（最被低估的差異）

| | ggml | ORT |
|---|---|---|
| 量化契約 | **硬性**：`ggml_type` 存在於型別系統，kernel 與佈局一一對應。不支援 = 編不過 / 載不進來 | **軟性**：量化是「圖重寫 + 算子」。EP 不支援 `MatMulNBits` 時可能**靜默 fallback** 到 dequant + FP32 matmul |
| 後果 | 錯誤在**編譯期/載入期**暴露 | 錯誤退化成**執行期效能崩塌**，且不會報錯 |

這是實務上最危險的差異：**ORT 的 fallback 機制保證「一定跑得動」，但可能慢 5–10 倍而毫無警告。** ggml 的嚴格性讓它「要嘛很快，要嘛根本跑不起來」——對生產環境，前者更安全；對通用平台，後者更安全。兩者都是理性選擇，但必須知道自己在哪一種。

### 9.5 可最佳化空間在哪一層：為什麼 llama.cpp 不是用 ORT 寫的

ORT 的最佳化發生在**圖層**（171 個 graph transformer：算子融合、CSE、constant folding、layout 轉換）。這些是**模型無關**的變換。

但 LLM 推論真正的大幅收益來自**執行策略**，而它們**不是圖變換**：

| LLM 關鍵最佳化 | 屬於哪一層 | ORT 圖層看得到嗎 |
|---|---|---|
| KV cache 的 paged / ring buffer 佈局 | 執行策略 | ❌ |
| FlashAttention 的 tiling 與 KV 分塊 | kernel 內部 | ⚠️ 只能當黑箱算子 |
| Speculative decoding（草稿模型 + 驗證） | 控制流 | ❌ 需多模型協作 |
| 連續 batching / paged attention 排程 | 執行策略 | ❌ |
| 量化權重的 GEMV 佈局融合 | 格式 + kernel | ⚠️ 需 MatMulNBits 支援 |

**技術論點 4：ORT 的抽象邊界（算子 = 最佳化單位）與 LLM 的最佳化邊界（跨算子的執行策略）不重合。** 這不是 ORT 做得不好，而是它的抽象層級是為「通用圖」設計的。llama.cpp 之所以存在，正是因為它把「執行策略」直接寫進程式，而不是寫進圖——代價是完全綁定特定架構。

反過來，**ORT 的價值也在同一個地方**：因為它抽象得夠高，才能一次支援 PyTorch / TF / sklearn / XGBoost 匯出的所有模型，並讓 Qualcomm、Intel、NVIDIA 各自維護 EP。**這是組織能力問題，不是技術能力問題。**

### 9.6 執行緒與同步模型

- **ggml**：單 backend 內用 spin-wait 執行緒池（`ggml-threading.cpp`），避免 futex 喚醒延遲；跨 backend 用 event（`ggml_backend_event_*`）同步。`GGML_OPENMP` 可選但預設走自製 pool。為「每步都要同步」的 decode 迴圈最佳化。
- **ORT**：EP 之間透過 device stream 與 `DataTransferManager` 同步，支援多 stream 並行；代價是同步點較多、跨裝置 copy 需要顯式管理（`IOBinding` 可繞過部分成本）。

**技術論點 5：decode 迴圈每步都要同步一次（取樣需要 logits），所以「同步延遲」直接乘上 token 數。** ggml 的 spin-wait 設計正是針對此；ORT 的通用同步機制在單模型低延遲場景是負擔。

### 9.7 建置期 / 啟動期的成本結構

| 階段 | ggml | ORT |
|---|---|---|
| 編譯時間 | 短（單一 C/C++ 庫，後端選配） | 很長（`build.py`、大量 flag、多平台工具鏈） |
| 二進位大小 | 幾 MB | 數百 MB |
| 模型載入 | `mmap`，幾乎 0 | 解析 protobuf/flatbuffer + 建圖 + 跑 171 個 optimizer + allocation planning |
| 改善手段 | 無需 | `.ort` 格式（flatbuffer，快載）、EP context 快取（預先編譯子圖） |
| ABI | 無（靜態連結，升版重編） | `OrtApi` 版本化函式表（`OrtGetApiBase`）→ 可換 shared lib 不重編 |

**技術論點 6：ORT 為「長時間運行、多次載入模型」的伺服器場景設計；ggml 為「單一模型、反覆推理」的邊緣場景設計。** 兩者的成本結構完全相反。

### 9.8 可證偽的預測（若日後實測，應驗證這些）

以下是我根據上述推導願意下注的預測，**標記為預測而非數據**：

| 情境 | 預測 | 驗證方法 |
|---|---|---|
| 同為 4-bit、batch=1、CPU decode | ggml 快於 ORT，差距 1.5–3× | `llama-bench -p 0 -n 128` vs ORT GenAI CPU |
| 同為 4-bit、batch=1、GPU decode | ggml 仍勝，但差距縮小（0–30%） | 需 CUDA build |
| prefill（pp512）CPU | 差距小，ORT 可能勝（MLAS/AMX 成熟） | `-p 512 -n 0` |
| batch ≥ 8 | ORT 反超（compute-bound，圖優化 + GEMM 效率主導） | 需 batching API |
| 冷啟動到第一 token | ggml 大幅勝（mmap 優勢） | 計時 |
| 模型換成非 transformer（CNN/傳統 ML） | ORT 壓倒性勝（ggml 缺算子） | 直接試 |

**判準：如果第一項預測不成立（ORT 在 batch=1 decode 上不落後），那我的 9.3(c) dispatch 推論就是錯的**，因為那代表 ORT 的逐節點開銷已被有效攤平。

### 9.9 本章結論（一句話）

> **在 decode 這個「頻寬受限」的階段，ggml 的優勢不是「寫得比較好」，而是「結構上不可能更差」——量化佈局、格式、kernel 三者合一，且沒有通用引擎的抽象稅。在 prefill 與多模型通用性這兩個「算力受限 / 多樣性受限」的維度，ORT 的優勢同樣是結構性的。兩者的勝負早已寫在設計裡，benchmark 只是確認。**

---

## 10. GGUF ↔ ORT 互通性（文件與原始碼查證）

> 問題：**ggml 的模型（GGUF）能轉成 ORT 嗎？**
> 答案：**可以，而且是官方支援——但方向與一般人想的相反。不是「把 ggml 轉成 ONNX」，而是「讓 ORT 直接吃 GGUF」。**

### 10.1 路徑 1：GGUF → 產生 ONNX 圖（模型建置期）

`onnxruntime-genai` 的 model builder 的 `-i/--input` 明確接受三種來源（`src/python/py/models/builder.py` 實測）：

```
hf_path:      Path to folder on disk containing the Hugging Face config, model, tokenizer, etc.
gguf_path:    Path to float16/float32 GGUF file on disk containing the GGUF model
oci://<registry>/<repo>:<tag>: CNCF ModelPack artifact
```

實作方式（`src/python/py/models/loaders/gguf.py`，18,337 bytes）：

> "A set of Python classes to mimic Hugging Face's PyTorch models with GGUF weights that are already in NumPy. The goal is for `GGUFModel` and a Hugging Face model produced by `AutoModel.from_pretrained(...)` to share the same attributes so that the original Hugging Face → ONNX code remains the same no matter where the weights actually come from."

即：用 `gguf.gguf_reader.GGUFReader` 讀 GGUF，**包裝成擁有相同 attribute 結構的假 HF 模型**（`q_proj`、`k_proj`、`mlp.gate_proj`…），於是既有的 HF→ONNX 建圖程式碼**一行都不用改**。

**限制**：輸入必須是 **F16 / F32 的 GGUF**（builder 說明原文）。不能直接餵 `Q4_K_M` 這種已量化檔——量化是在建圖後的 `--precision` / `--target_options` 階段做。

### 10.2 路徑 2：ONNX 圖 + GGUF 權重分離（執行期，零轉換）

`onnxruntime-genai/docs/GGUFInitializers.md` 原文：

> "ONNX Runtime GenAI supports loading ONNX model initializers directly from GGUF v2/v3 weight files (`.gguf`), eliminating the need to duplicate model weights into `.onnx.data` external data files."

在 `genai_config.json` 的 `model.decoder` / `draft` / `dflash2` / `mtp` 段落加 `"gguf_initializers"`，可為外部 JSON 檔或 inline 物件：

```json
"decoder": {
  "filename": "model.onnx",
  "gguf_initializers": {
    "files": ["model.gguf"],
    "share": false,
    "tensors": {
      "embed_tokens": { "gguf_name": "token_embd.weight", "share": true },
      "lm_head.weight": "output.weight"
    }
  }
}
```

支援欄位包含 `gguf_name`、`data_type`、`shape`（可重新詮釋 3D 打包張量）、`share`（多模型共用同一份 device 記憶體）。

**這是最乾淨的路徑：ONNX 只存「圖」，權重留在 GGUF 裡，`mmap` 直讀，不複製不轉換。**
與 `docs/Model_Loading_Performance.md` 的 `session.use_external_initializer_file_buffers_directly` 搭配，可讓 ORT 直接借用 mmap 緩衝區（零 copy）。

**限制（原文）**：pipelined decoder 與 `streaming_enc_dec_asr`（Moonshine）不支援 GGUF 映射，會明確拒絕。

### 10.3 路徑 3：ORT 把 GGUF 佈局寫成「格式契約」（最深的整合）

`microsoft/onnxruntime/docs/PackedWeightFormats.md` 是一份**正式的格式契約**，定義三個 `com.microsoft` 算子的 packed 權重格式：

- `MatMulPacked`
- `GatherPacked`
- `MoEPacked`

它明確 pin 在 llama.cpp commit `970b51ce7c9ba5fff0726c5e9994f1c2f0e4eedc`，並以 `gguf-py/gguf/quants.py` 作為獨立解碼器來驗證 ORT 的 fixed known-answer tests。

原文最關鍵的一段：

> "The IDs, block layouts, quantization arithmetic, and codebooks below are stable ORT model-format meanings, not a request to interpret whichever ggml enum or decoder happens to be current. ORT updates must preserve these meanings for existing models. An incompatible layout, codebook, or decoding change requires a new format ID or operator version; **an upstream enum or layout change must not silently reinterpret an existing ORT model.**"

**這是 ORT 對 ggml 的一次重大架構讓步**：把 ggml 的 block 佈局「凍結」成自己的格式語意，從此 ggml 上游改動不得影響 ORT 模型。

#### 支援的 ggml type ID（實測表格）

| ID | 型別 | elems/block | bytes/block |
|---:|---|---:|---:|
| 0 | F32 | 1 | 4 |
| 1 | F16 | 1 | 2 |
| 2 | **Q4_0** | 32 | 18 |
| 6 | Q5_0 | 32 | 22 |
| 8 | Q8_0 | 32 | 34 |
| 13 | Q5_K | 256 | 176 |
| 14 | Q6_K | 256 | 210 |
| 16 | IQ2_XXS | 256 | 66 |
| 17 | IQ2_XS | 256 | 74 |
| 18 | IQ3_XXS | 256 | 98 |
| 20 | IQ4_NL | 32 | 18 |
| 22 | IQ2_S | 256 | 82 |
| 23 | IQ4_XS | 256 | 136 |
| 30 | BF16 | 1 | 2 |
| 40 | NVFP4 | 64 | 36（僅 CUDA MatMulPacked） |
| 42 | Q2_0 | 64 | 18 |

#### 最重要的缺口：**`Q4_K`（ID 12）不在支援清單**

文件原文：「Only the IDs in this table are supported… All other values, including unlisted IDs in the range `0..99`, negative IDs, and IDs `>=100`, are unsupported and rejected.」

**也就是說，生態中最普及的 `Q4_K_M` 反而不被支援。** 想走 ORT 的 packed 路線，實務上要改用：
- `Q5_K_M`（ID 13）或 `Q6_K`（ID 14），或
- `Q4_0`（ID 2，但品質較差）

這是一個非常容易被踩到的坑：**「ORT 支援 GGUF」不等於「ORT 支援你手上的那個 GGUF」。**

### 10.4 路徑 4：GGUF → HF → ONNX（不推薦）

- llama.cpp **只有單向**的 `convert_hf_to_gguf.py`；repo 內其他轉換腳本是 `convert_hf_to_gguf_update.py`、`convert_llama_ggml_to_gguf.py`（舊格式升級）、`convert_lora_to_gguf.py`。
- **沒有官方 `convert_gguf_to_hf.py`**。GitHub 上有多個社群版本（`nbllt666/CX-O`、`CodeOfMe/FanFu`、`Thaman-N/ACAS`、`pikasTech/mimibot-factory` 等），品質與維護狀態不一，無測試保證。
- 流程：反量化回 F16/BF16 → 存 HF safetensors → 匯出 ONNX。
- 缺點：**反量化→再量化造成二次精度損失**、耗時、需要約 2× 磁碟空間、且必須先知道原模型架構（GGUF metadata 才有）。

### 10.5 反向：ORT / ONNX → ggml

- llama.cpp 的 `convert_llama_ggml_to_gguf.py` 是「舊 GGML 格式 → GGUF」，不是 ONNX → GGUF。
- 社群有 `onnx2gguf`（FastChat 時代產物），僅支援 LLaMA 架構，已過時。
- **實務上不建議、也不可靠。**

### 10.6 結論

| 你的需求 | 建議路徑 | 限制 |
|---|---|---|
| 想用 ORT 引擎跑手上的 GGUF | **路徑 2**（`gguf_initializers`），零轉換 | 不支援 pipelined decoder / Moonshine ASR |
| 想產出正式可發佈的 ONNX 模型 | **路徑 1**（builder `-i xx.gguf`） | 輸入須 F16/F32 GGUF |
| 想用 `Q4_K_M` | ❌ **不支援**，改 `Q5_K_M` / `Q6_K` / `Q4_0` | 見 10.3 表格 |
| 需要任意 GGUF 量化格式（TQ/IQ1/Q1_0…） | 留在 llama.cpp | ORT 僅支援 16 種 ID |
| 想完整保留原模型架構 | 路徑 1 或 2 | 需 GGUF metadata 完整 |

### 10.7 對第 7 節「趨勢判讀」的修正

先前基於 commit 訊息推論「ORT 開始吃 GGUF，邊界在模糊」。現在有文件級證據，結論要升級：

> **不是「邊界模糊」，而是 ORT 已經把 ggml 的量化佈局納入自己的模型格式契約（`PackedWeightFormats.md`），並把 GGUF 當成一等公民的權重來源（`GGUFInitializers.md`）。**
> 同時 ORT 刻意「凍結」佈局語意，明確拒絕跟隨 ggml 上游變動——這是在**吸收 ggml 的成果，同時切斷對 ggml 的依賴**。
> 這比單純「支援 GGUF」嚴重得多：它代表 ggml 花了三年建立的量化格式生態，正在被 ORT 以「格式契約」的方式收割。

---

## 11. 本次分析的已知限制

- 未實際編譯、未跑 benchmark：**所有效能敘述皆為架構推論，非實測數據。** 第 9.8 節已把可驗證的預測單獨列出，避免與事實混淆。
- 未逐一檢視各 backend 的完成度（例如 `ggml-hexagon`、`ggml-vsinpu` 的成熟度差異可能很大）。
- ORT 的 171 個 optimizer 僅抽樣；EP 的實際 opset 覆蓋率未量化。
- Star / 貢獻者為 2026-11-12 快照，會變動。

---

## 12. 路徑 2 落地實作：`gguf_initializers` 完整規格與實務條件

> 本章為第 10.6 節「路徑 2（直接吃 GGUF 量化權重）」的展開。所有敘述來自 `docs/GGUFInitializers.md`（108 行全文）、`test/cpp/engine/gguf_initializers_tests.cpp`、`docs/NemotronBolt.md`、`src/config.{h,cpp}`、`src/models/model.cpp` 與 ORT 的 `contrib_ops/cuda/quantization/matmul_packed.*`。**仍未實測。**

### 12.1 官方 schema 全貌

可掛載位置（四個）：

| 位置 | 用途 |
| --- | --- |
| `model.decoder` | 主解碼器 |
| `model.draft` | 投機解碼 drafter |
| `model.dflash2` | DFlash2 drafter（Nemotron Bolt 用法） |
| `model.mtp` | Multi-Token Prediction 頭 |

支援範圍與拒絕條件（原文）：

- 對應到**所有 decoder session**，含獨立設定的 speech decoder 與 Nemotron Parse prefill session。
- **不支援**：pipelined decoder、`streaming_enc_dec_asr`（Moonshine）——會明確報錯拒絕，不是靜默降級。

兩種寫法：

1. `"gguf_initializers": "gguf_initializers.json"`（相對 `genai_config.json` 的路徑）
2. `"gguf_initializers": { ... }`（inline 物件）

外部映射檔**不能**再寫 `config_file`（禁止嵌套映射，直接拒絕）。

欄位表（共 7 個，**每個欄位只有唯一拼法，未知欄位一律拒絕**）：

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `config_file` | string | 可選，指向外部 JSON 映射檔（相對路徑） |
| `files` | string[] | 一個或多個 `.gguf`（相對路徑），供未指定 `file` 的張量搜尋；同一檔案的別名會去重，**跨檔案命中多筆 → 以 ambiguous 拒絕** |
| `share` | bool | 跨 session 裝置共享的預設值（預設 `false`） |
| `tensors` | object | **ONNX initializer 名 → GGUF 張量名（字串）或映射物件** |
| `tensors.<name>.gguf_name` | string | 映射物件中必填 |
| `tensors.<name>.file` | string | 指定該張量來自哪個 shard |
| `tensors.<name>.data_type` | int | `ONNXTensorElementDataType` 覆寫；預設由 GGUF 型別自然對應：`F32→FLOAT`、`F16→FLOAT16`、`BF16→BFLOAT16`、**block-quant → `UINT8`** |
| `tensors.<name>.shape` | int64[] | ONNX 形狀覆寫；`[]` 表示 rank-0 純量；**必須與 GGUF 張量的位元組數完全相等** |

預設 `shape` 規則（關鍵）：

```
區塊量化： [dims[n-1], ..., dims[1], (dims[0] / blck_size) * type_size]
非量化：   [dims[n-1], ..., dims[0]]
```

也就是說：**ONNX 端看到的是「整個 GGUF blob 攤平成一個 initializer」**，最後一維不是 `in_features`，而是「block 數 × 每個 block 的位元組數」。

實例（Q4_0，`blck_size=32`、`type_size=18`）：

- GGUF `blk.0.attn_q.weight` 的 dims = `[4096, 4096]`（ggml 順序：in, out）
- 預設 shape = `[4096, (4096/32)*18]` = `[4096, 2304]`
- 位元組數 = `4096 × 2304 = 9,437,184` = `4096 × 4096 / 32 × 18` ✓

K-quant 的 `blck_size = 256`（`Q4_K` type_size=144、`Q5_K`=176、`Q6_K`=210），但**`Q4_K` 不在 ORT 支援清單**（見第 10.3 節）。

### 12.2 最小可用範例（依 schema 重構，非官方原文）

`genai_config.json`：

```json
{
  "model": {
    "type": "llama",
    "vocab_size": 128256,
    "context_length": 8192,
    "decoder": {
      "filename": "model.onnx",
      "session_options": { "intra_op_num_threads": 1 },
      "gguf_initializers": "gguf_initializers.json"
    }
  },
  "search": {}
}
```

`gguf_initializers.json`：

```json
{
  "files": ["Meta-Llama-3.1-8B-Instruct-Q4_0.gguf"],
  "tensors": {
    "embed_tokens": { "gguf_name": "token_embd.weight", "share": true },
    "lm_head.weight": "output.weight",
    "final_norm": "output_norm.weight",
    "language_model.layers.0.self_attn.q_proj.weight": "blk.0.attn_q.weight",
    "language_model.layers.0.self_attn.k_proj.weight": "blk.0.attn_k.weight",
    "language_model.layers.0.self_attn.v_proj.weight": "blk.0.attn_v.weight",
    "language_model.layers.0.self_attn.o_proj.weight": "blk.0.attn_output.weight",
    "language_model.layers.0.mlp.gate_proj.weight": "blk.0.ffn_gate.weight",
    "language_model.layers.0.mlp.up_proj.weight": "blk.0.ffn_up.weight",
    "language_model.layers.0.mlp.down_proj.weight": "blk.0.ffn_down.weight"
  }
}
```

要點：

- 映射物件的長格式只在需要 `file` / `data_type` / `shape` / `share` 時使用；其餘一律可寫成短格式 `"onnx_name": "gguf.name"`。
- **只驗證被映射選到的張量**。同一個 GGUF 內含 loader 不支援的型別沒關係，只要沒被選到；一旦選到，錯誤訊息會指名張量與檔案。
- 若要省掉外部檔案，可把整個物件 inline 進 `genai_config.json`，或在外層用 `"config_file": "..."`。

### 12.3 張量名稱對映規則

兩側命名體系完全不同，**必須逐個對映，沒有自動推導規則**：

| 側 | 命名來源 | 範例 |
| --- | --- | --- |
| ONNX（JSON 的 key） | 圖作者／builder 決定，**任意合法名稱** | `language_model.backbone.layers.0.norm.weight`、`l1.fc1_w`、`embed_tokens` |
| GGUF（`gguf_name`） | ggml 固定慣例 | `token_embd.weight`、`blk.0.attn_norm.weight`、`blk.1.ffn_up_exps.weight` |

LLaMA 系常見對照（HF 名 → ggml 名，僅供推導 ONNX 側時的參考）：

| HF | ggml |
| --- | --- |
| `model.embed_tokens.weight` | `token_embd.weight` |
| `model.norm.weight` | `output_norm.weight` |
| `lm_head.weight` | `output.weight` |
| `model.layers.N.input_layernorm.weight` | `blk.N.attn_norm.weight` |
| `model.layers.N.post_attention_layernorm.weight` | `blk.N.ffn_norm.weight` |
| `model.layers.N.self_attn.{q,k,v,o}_proj.weight` | `blk.N.attn_{q,k,v,output}.weight` |
| `model.layers.N.mlp.{gate,up,down}_proj.weight` | `blk.N.ffn_{gate,up,down}.weight` |
| MoE 專家 | `blk.N.ffn_{gate,up,down}_exps.weight`（3D，需 `shape` 覆寫） |
| MoE router | `blk.N.ffn_gate_inp.weight` |

Nemotron Bolt 的官方範例顯示 ONNX 側可以完全自訂（`embed_tokens`、`l0.in_proj.fp4`、`l1.fc1_w`），並在 3D 專家張量上手動給 `"data_type": 2, "shape": [240, 1536, 264]`。

### 12.4 三種載入行為

1. **mmap 快取**：每個 `.gguf` 以唯讀方式映射一次（POSIX `mmap(PROT_READ, MAP_SHARED)`），並依檔案身分（`st_dev:st_ino`）快取解析後的 tensor directory。分頁按需載入、可被 OS 回收；最後一個使用該檔的 model 銷毀前映射保持有效。
2. **`share: false`（直接注入）**：`Model::AddGgufInitializers` 建立指向映射區的 non-owning CPU `OrtValue`，設定 `session.use_external_initializer_file_buffers_directly = "1"`，經 `SessionOptions::AddExternalInitializers` 注入。
   - **要真正 zero-copy，ORT 必須 ≥ 1.32.0**（PR #33877）；更舊的版本對這條路徑一律複製。
   - 即使在 1.32+，也只在「張量 > 127 bytes、資料位址為元素大小的倍數、little-endian」時才借用，其餘複製。GGUF 預設 32-byte 對齊，通常沒問題。
   - 借用只省掉 CPU 端重複副本；EP 仍會在 session 建立時上傳到裝置記憶體。
3. **`share: true`（跨 session 裝置共享）**：直接從映射檔上傳一次到裝置記憶體，快取於 `g_shared_initializers`，再以 `SessionOptions::AddInitializer` 綁進多個 session（目標解碼器 + DFlash2/MTP drafter）。上傳後不留 host staging 副本。快取會區分 allocator 名稱與 device id。**DML 直接拒絕**（allocator 會在共享張量仍存活時關閉），CPU 上則忽略此旗標。

### 12.5 硬性前提與實務斷點（本章重點）

`gguf_initializers` 解決的是「**權重怎麼進來**」，不是「**圖怎麼來**」。要真的跑起來，還缺三塊，而這三塊目前都缺：

| 前提 | 現況 | 證據 |
| --- | --- | --- |
| 圖的權重必須以 **`MatMulPacked`**（單一 GGUF blob、`UINT8`）消費 | `MatMulPacked` **只有 CUDA kernel** | 僅在 `onnxruntime/contrib_ops/cuda/quantization/matmul_packed.{h,cc,cu}` 實作，只在 `cuda_contrib_kernels.cc` 註冊 |
| builder 能產出 packed 圖 | **完全不能** | `builder.py` / `builders/base.py` grep `MatMulPacked|GatherPacked|MoEPacked` → 0 筆；genai Python 端整體 0 筆 |
| ORT 能把既有 int4 圖轉成 packed | **沒有這個融合** | `core/optimizer/` 只有 `dq_matmulnbits_fusion`、`matmul_nbits_{fusion,mlp_fusion,qkv_fusion,qlora_fusion}`，無 nbits→packed |

builder 的 int4 路徑實際產出的是 **`MatMulNBits` 三分量佈局**：`algo_config ∈ {default, rtn, k_quant}`，底層都是 `MatMulNBitsQuantizer`；`k_quant` 走 Neural Compressor 的 `KQuantWeightOnlyQuantConfig`，輸出 `*.MatMul.weight_Q4G32`、`*.MatMul.weight_scale`、`*.MatMul.weight_zp`。scale 是**獨立 initializer**，而 `MatMulPacked` 的 block 內含 `d`（scale）——**兩者佈局不相容**。

**結論（修正第 10.6 節的樂觀程度）：**

> 路徑 2 是「模型發佈方預先備好 packed 圖 + 手寫對映 JSON」的**特定模型專用通道**，不是通用「拿任何 GGUF 丟給 ORT」的方案。
> 目前公開可見的唯一完整實例是 **Nemotron-3.5-Bolt-74B-A9B-24GB**：843 個 target 權重張量全部從 GGUF 直載，外加兩份 JSON（`gguf_initializers.json` + `dflash2_gguf_initializers.json`），其中 `token_embd.weight` 與 `output.weight` 標 `"share": true` 在 target 與 drafter 間共用一份 GPU 配置。
> 對一般使用者而言，這條路目前**沒有自助入口**——你得自己造 packed 圖，官方工具鏈不幫你做。

對本機（RTX 4050 Laptop 6 GB、無 `nvcc`、無 `cmake`）而言：`MatMulPacked` 只有 CUDA kernel，**路徑 2 直接不可用**。

### 12.6 決策表補註（覆寫第 10.6 節「路徑 2」一行）

| 情境 | 可行性 |
| --- | --- |
| 手上是 Nemotron Bolt 這類官方已發布 packed 套件 | ✅ 可用（CUDA） |
| 想用任意 `Q4_0` GGUF + 官方 builder 產的圖 | ❌ 圖是 `MatMulNBits`，佈局不符 |
| 只有 CPU / DML | ❌ `MatMulPacked` 無 CPU kernel；DML 拒絕共享張量 |
| 願意自建 CUDA ORT + 自造 packed 圖 | ⚠️ 理論可行，工程量等同做一個新後端 |

### 12.7 若堅持走這條路的最小工作項（未執行，僅列）

1. 建置含 CUDA EP 的 ORT（需 `nvcc`、`cmake`）。
2. 取得或自製 `MatMulPacked` 版 ONNX 圖（目前無公開轉換工具）。
3. dump 兩側張量名：ONNX `graph.initializer` 清單 ↔ GGUF tensor directory。
4. 產生對映 JSON（官方無產生器；可自寫腳本，但 `shape` 需按 12.1 公式計算並驗證位元組數相等）。
5. 驗證：`shape` 乘積必須**精確等於** GGUF 張量位元組數，否則載入期就會失敗。

### 12.8 重現指令

```bash
gh api repos/microsoft/onnxruntime-genai/contents/docs/GGUFInitializers.md \
  -H "Accept: application/vnd.github.raw"
gh api repos/microsoft/onnxruntime-genai/contents/test/cpp/engine/gguf_initializers_tests.cpp \
  -H "Accept: application/vnd.github.raw" | grep -n "gguf_initializers"
gh search code "MatMulPacked" --repo microsoft/onnxruntime --limit 20
gh search code "MatMulPacked" --repo microsoft/onnxruntime-genai --limit 20   # 空 = 無支援
```

---

## 13. 研究路線決策：ggml 優先，穩定後再評估 ORT

### 13.1 決策

> **以 ggml 為主要研究與實作目標；待 ggml 路線「可用且穩定」後，再評估是否遷移到 ONNX Runtime。**

### 13.2 為何這個順序是對的（三點，皆有前文證據）

1. **格式與量化的源頭在 ggml。** GGUF、Q4_0/Q4_K/IQ 系列、block 佈局全部由 ggml 定義（第 4、9 章）。先掌握源頭，等於先掌握「模型長什麼樣」。
2. **ORT 對 GGUF 的吸收是單向的。** ORT 把 ggml 的佈局寫成自己的契約（`PackedWeightFormats.md`）並凍結語意（第 10.7 節），但**沒有反向路徑**（第 10.6 節、12.5 節）。先做 ggml 是站在上游；先做 ORT 則會被綁在沒有出口的下游。
3. **本機現實。** 6.1 GB VRAM、無預裝 CUDA toolkit、WSL2——這個環境要「先跑起來」，ggml/llama.cpp 的建置門檻遠低於 ORT GenAI（後者要 builder + EP + 對映 JSON，且路徑 2 需要自造 packed 圖）。

### 13.3 名詞先釐清：ggml 本身不是推論引擎

| 目標 | 該用哪個 repo | 說明 |
| --- | --- | --- |
| 讀架構、寫 kernel、研究張量抽象 | `ggml-org/ggml` | 有 `gpt-2`、`gpt-j`、`mnist`、`sam`、`yolo`、`magika` 等 example，可獨立跑小模型 |
| 跑現代 LLM（Llama/Qwen/Gemma 等） | `ggml-org/llama.cpp` | **vendored ggml**；`examples/` 內沒有 llama，LLM 推論能力都在 llama.cpp |

→ 「以 ggml 為主要研究目標」若包含**跑真實 LLM**，實務上必須用 llama.cpp（它內嵌同一份 ggml）。兩者不是二選一，而是「同一技術棧的兩層」。

### 13.4 本機環境實測（2026-11-12，WSL2）

| 項目 | 狀態 | 影響 |
| --- | --- | --- |
| 平台 | **WSL2**（`6.18.33.2-microsoft-standard-WSL2`） | GPU 透過 Windows 驅動直通 |
| GPU | RTX 4050 Laptop, **6141 MiB**, driver 610.91 | `nvidia-smi` 可用 |
| `cmake` | **未安裝** | ggml 必需（`cmake_minimum_required 3.14`）→ 需 `apt install cmake` |
| `nvcc` | 未安裝，**但可安裝** | WSL 內裝 `cuda-toolkit` 不需 Windows 驅動 → `GGML_CUDA=ON` **可行** |
| Vulkan ICD | 有 mesa 的 `nouveau/intel/radeon/lvp`，**缺 dzn / nvidia** | Vulkan 後端目前不可用；需 `mesa-vulkan-drivers`+`vulkan-tools` 才能驗證 |
| 記憶體 | 31 GiB | CPU 推論可吃到 13B Q4（約 8 GB） |
| 編譯器 | gcc 13.3、make | 足夠 |

**結論**：先前「無 nvcc → GPU 不可行」的判斷要修正——`nvcc` 是**套件問題**，不是硬體問題。真正要先裝的是 `cmake`。

### 13.5 兩個不可逆決策（決定日後遷移成本）

1. **保留 F16 GGUF 作為唯一真實來源。**
   不要從 `Q4_K_M` 反量化再量化到別的格式——那會產生二次量化損失。正確做法：HF checkpoint（或轉出的 F16 GGUF）留存，`Q4_K_M`（ggml 用）與 int4 ONNX（未來 ORT 用）**各自從 F16 產出**。
2. **ggml 端量化選型不受 ORT 約束，但 F16 必須留。**
   `Q4_K_M` 在 ggml 是最好的性價比；即使 ORT 不支援 `Q4_K`（ID 12 缺席），只要保留 F16，未來仍可用 builder 重新產生 ORT 模型（第 10.6 節路徑 1）。**F16 在，路線就不會被鎖死。**

### 13.6 三階段計畫與驗收標準

| 階段 | 工作 | 驗收標準 |
| --- | --- | --- |
| **P1 可跑** | `apt install cmake build-essential` → 建 llama.cpp（CPU, `GGML_NATIVE=ON`）→ 跑 7B/8B `Q4_K_M` | 能生成連貫輸出；`llama-bench` 有數字 |
| **P2 用得上** | 裝 `cuda-toolkit` → `GGML_CUDA=ON` 重建 → 部分層 offload（`-ngl 20~28`） | 6.1 GB VRAM 不 OOM；tokens/s 明顯高於 CPU |
| **P3 研究** | 讀 `src/` 五大抽象與 backend 註冊、量化 block 結構、`ggml_backend_sched` 排程 | 能自己寫一個 ggml example 或改一個 kernel |

預期量級（依第 9.2 節公式推算，非實測）：

| 配置 | 有效頻寬（估） | 8B Q4_K_M（≈4.87 GB）解碼上限 |
| --- | --- | --- |
| CPU（DDR5 雙通道） | 60–70 GB/s | ~12–14 tok/s |
| RTX 4050（192 GB/s） | 150–180 GB/s | ~30–37 tok/s |

6.1 GB VRAM 扣掉 KV cache 與 CUDA context 後，8B 全量 offload 很貼邊——**先用 7B 或 `-ngl 24` 部分 offload 起步**。

### 13.7 「ggml 已穩定」的判準（何時才算可以轉 ORT）

- [ ] 同一份 F16 GGUF 能穩定產出 `Q4_K_M` 並可重現（bit-identical 或誤差可解釋）
- [ ] 推論結果有 golden 對照（同 prompt、同 seed、固定 token 數）
- [ ] 建置流程腳本化（可從乾淨環境重建）
- [ ] 已知限制寫清楚（哪些量化在某機器上會退回純 CPU 路徑）
- [ ] 有一套「模型資產目錄」慣例（F16 原始、量化版、config、tokenizer 分開放）

達成後再談 ORT：屆時走**路徑 1（F16 GGUF → builder）**，而不是路徑 2（第 12.5 節已證明沒有自助入口）。
