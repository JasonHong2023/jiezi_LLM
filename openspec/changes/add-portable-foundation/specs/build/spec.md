# build Specification

## ADDED Requirements

### Requirement: Pinned Source

系統 SHALL 依 `openspec/specs/stack.md` 鎖定的 llama.cpp commit 取得原始碼至 `vendor/llama.cpp`（不進版控），任何機器取得的原始碼都必須一致。
The system SHALL fetch llama.cpp into `vendor/llama.cpp` (not versioned) at the commit pinned in `openspec/specs/stack.md`, so every machine gets identical sources.

#### Scenario: 乾淨電腦 / Clean machine

- **WHEN** `vendor/llama.cpp` 不存在
  `vendor/llama.cpp` does not exist
- **THEN** 系統以鎖定的 commit 取得原始碼，並驗證 `HEAD` 等於該 commit
  The system fetches the sources at the pinned commit and verifies that `HEAD` equals that commit

#### Scenario: 已存在但 commit 不符 / Present but at the wrong commit

- **WHEN** `vendor/llama.cpp` 的 `HEAD` 不等於鎖定的 commit
  The `HEAD` of `vendor/llama.cpp` differs from the pinned commit
- **THEN** 系統停止並說明差異，不自動覆蓋（升級 commit 屬重大變更，須依規則 R4、R17.3 處理）
  The system stops and explains the mismatch without overwriting (changing the commit is a major change under rules R4 and R17.3)

### Requirement: Detection-Driven Backend Selection

系統 SHALL 依 `facts.json` 的 `backends.buildable` 決定建置哪些後端：CPU 後端一律建置；其他後端只在 `ok` 為 `true` 時建置；每個後端的「建置 / 略過」及原因都要輸出。
The system SHALL choose backends from `backends.buildable` in `facts.json`: the CPU backend is always built; other backends are built only when `ok` is `true`; each backend's build/skip decision and reason are reported.

#### Scenario: 有 CUDA 的機器 / Machine with CUDA

- **WHEN** `backends.buildable.cuda.ok` 為 `true`
  `backends.buildable.cuda.ok` is `true`
- **THEN** 系統建置 `build-cpu` 與 `build-cuda`
  The system builds `build-cpu` and `build-cuda`

#### Scenario: 沒有 GPU 的機器 / Machine without a GPU

- **WHEN** 所有加速後端的 `ok` 都為 `false`
  Every accelerator backend has `ok` set to `false`
- **THEN** 系統只建置 `build-cpu`，並列出各加速後端略過的原因，整體視為成功
  The system builds only `build-cpu`, lists why each accelerator was skipped, and the run counts as a success

### Requirement: Portable Build Flags

建置旗標 SHALL 不含任何寫死的硬體型號：CPU 用 `-DGGML_NATIVE=ON`；CUDA 用 `-DCMAKE_CUDA_ARCHITECTURES=native`；`nvcc` 路徑取自 `facts.json` 的 `backends.toolchain.nvcc`。
Build flags SHALL contain no hardcoded hardware models: CPU uses `-DGGML_NATIVE=ON`; CUDA uses `-DCMAKE_CUDA_ARCHITECTURES=native`; the `nvcc` path comes from `backends.toolchain.nvcc` in `facts.json`.

#### Scenario: 不同 GPU 架構 / Different GPU architecture

- **WHEN** 在不同世代的 NVIDIA GPU 上建置
  Building on a different generation of NVIDIA GPU
- **THEN** 建置旗標不需修改，CUDA 架構由編譯器自行偵測
  The build flags need no changes; the compiler detects the CUDA architecture itself

### Requirement: Resource-Bounded Build

建置 SHALL 遵守資源預算：平行工作數取 `budgets.cpu.usable_threads`，以 `nice` 降低優先權，可取得 `affinity_hint` 時以 `taskset` 綁定（規則 R18.1、R18.2）。
Builds SHALL respect the resource budget: parallel jobs come from `budgets.cpu.usable_threads`, priority is lowered with `nice`, and `taskset` pins to `affinity_hint` when available (rules R18.1, R18.2).

#### Scenario: 預算限制 / Budget limits

- **WHEN** `usable_threads` 為 12
  `usable_threads` is 12
- **THEN** 建置使用 `-j 12`，且不使用被保留的核心
  The build uses `-j 12` and does not use the reserved cores

#### Scenario: 拓撲不可得 / Topology unavailable

- **WHEN** `affinity_hint` 為 `null`
  `affinity_hint` is `null`
- **THEN** 建置仍以 `usable_threads` 限制工作數，只是不綁定 CPU，並在輸出中註明
  The build still limits jobs to `usable_threads`, skips CPU pinning, and notes this in its output

### Requirement: Build Record

每次建置 SHALL 寫出建置紀錄（不進版控）：llama.cpp commit、各後端的 CMake 旗標、編譯器與 CUDA 版本、耗時、結果、機器指紋 `fingerprint.id`，供量測時引用（規則 R17.1）。
Every build SHALL write a build record (not versioned): llama.cpp commit, per-backend CMake flags, compiler and CUDA versions, duration, result, and machine `fingerprint.id`, for measurements to cite (rule R17.1).

#### Scenario: 建置完成 / Build finished

- **WHEN** 任一後端建置完成或失敗
  Any backend build finishes or fails
- **THEN** 建置紀錄包含該後端的結果與上述欄位
  The build record contains that backend's result and the fields above

### Requirement: No Vendor Modification

系統 SHALL NOT 直接修改 `vendor/llama.cpp`；若日後需要對上游修正，必須存成 `patches/*.patch` 並在建置時套用與記錄（規則 R6.2）。
The system SHALL NOT edit `vendor/llama.cpp` directly; any future upstream fix must live in `patches/*.patch` and be applied and recorded at build time (rule R6.2).

#### Scenario: 原始碼被改動 / Sources modified

- **WHEN** 建置前 `vendor/llama.cpp` 有未提交的改動
  `vendor/llama.cpp` has uncommitted changes before building
- **THEN** 系統停止並列出改動的檔案
  The system stops and lists the modified files
