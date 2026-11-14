# hwprobe Specification

## ADDED Requirements

### Requirement: Facts Snapshot

系統 SHALL 提供唯讀探測器 `scripts/hwprobe.py`，輸出單一 JSON 檔（`facts.json`），作為所有下游決策的唯一事實來源。
The system SHALL provide a read-only probe `scripts/hwprobe.py` that writes a single JSON file (`facts.json`) as the sole source of facts for all downstream decisions.

#### Scenario: 正常執行 / Normal run

- **WHEN** 使用者在支援的 Linux / WSL2 環境執行 `scripts/hwprobe.py`
  The user runs `scripts/hwprobe.py` on a supported Linux / WSL2 machine
- **THEN** 產生含 `schema_version`、`generated_at`、`fingerprint`、`host`、`cpu`、`memory`、`gpus`、`npus`、`backends`、`budgets`、`verdict`、`probe_failures` 的 JSON
  A JSON file is produced containing `schema_version`, `generated_at`, `fingerprint`, `host`, `cpu`, `memory`, `gpus`, `npus`, `backends`, `budgets`, `verdict`, and `probe_failures`

#### Scenario: 單一探測失敗不影響其他區塊 / One failing probe does not affect the rest

- **WHEN** 某個探測維度失敗（例如 `nvidia-smi` 不存在，或探測函式拋出例外）
  One probe dimension fails (e.g. `nvidia-smi` is absent, or a probe function raises)
- **THEN** 該區塊輸出 `present: false` 與 `reason`；例外訊息記入 `probe_failures`；其餘區塊照常輸出；exit code 為 0
  That block reports `present: false` with a `reason`; the exception message goes into `probe_failures`; the other blocks are still produced; the exit code is 0

### Requirement: Source Attribution

每一項事實 SHALL 標註其來源（`source` 欄位），每一項「不存在」SHALL 附 `reason`。
Every fact SHALL carry its source (`source` field), and every "absent" result SHALL carry a `reason`.

#### Scenario: GPU 事實 / GPU facts

- **WHEN** 系統存在 NVIDIA GPU
  The system has an NVIDIA GPU
- **THEN** `gpus.gpus[].source` 為 `nvidia-smi`，且 `vram_total_mib` / `vram_free_mib` 與 `nvidia-smi` 輸出相符
  `gpus.gpus[].source` is `nvidia-smi`, and `vram_total_mib` / `vram_free_mib` match the `nvidia-smi` output

### Requirement: NPU Detection

系統 SHALL 以 Linux 標準介面（`/sys/class/accel`、PCI processing accelerator）判定 NPU 存在性，而非依賴廠商工具。
The system SHALL detect NPUs through standard Linux interfaces (`/sys/class/accel`, PCI processing accelerators) rather than vendor tools.

#### Scenario: 無 NPU 的機器 / Machine without an NPU

- **WHEN** `/sys/class/accel` 不存在或為空，且 PCI 沒有 processing accelerator 裝置
  `/sys/class/accel` is absent or empty, and no PCI processing accelerator exists
- **THEN** `npus.present` 為 `false`、`npus.npus` 為空陣列，且 `npus.reason` 說明判定依據
  `npus.present` is `false`, `npus.npus` is empty, and `npus.reason` explains the basis

#### Scenario: 有 NPU 的機器 / Machine with an NPU

- **WHEN** 存在 `accel` 類裝置或 PCI processing accelerator
  An `accel`-class device or a PCI processing accelerator exists
- **THEN** `npus.npus` 列出每個裝置的名稱與來源
  `npus.npus` lists each device's name and source

### Requirement: Backend Buildability

系統 SHALL 區分「後端可用（已有可執行的 binary）」與「後端可建置（環境具備編譯條件）」，不得混為一談。
The system SHALL distinguish "backend available (a runnable binary exists)" from "backend buildable (the toolchain is present)" and MUST NOT conflate them.

#### Scenario: 尚未建置 llama.cpp / llama.cpp not built yet

- **WHEN** 專案內不存在任何 llama.cpp binary
  No llama.cpp binary exists in the project
- **THEN** `backends.available` 為空，`backends.buildable` 依環境列出 `cpu` / `cuda` / `vulkan` / `openvino` 各自的 `ok` 與 `reason`
  `backends.available` is empty, and `backends.buildable` lists `ok` and `reason` for each of `cpu` / `cuda` / `vulkan` / `openvino`

#### Scenario: 已建置 CUDA 後端 / CUDA backend built

- **WHEN** `build-cuda/bin/llama-cli --list-devices` 列出 CUDA 裝置
  `build-cuda/bin/llama-cli --list-devices` lists a CUDA device
- **THEN** `backends.available` 含該裝置名稱（例如 `CUDA0`），且 `verdict.primary_device` 為該裝置
  `backends.available` contains that device name (e.g. `CUDA0`), and `verdict.primary_device` is that device

### Requirement: CUDA Toolkit Discovery

系統 SHALL 不只在 `PATH` 中尋找 `nvcc`，而是依序檢查：`PATH`、`CUDA_HOME/bin`、`CUDA_PATH/bin`、`/usr/local/cuda/bin`、`/usr/local/cuda-*/bin`（取版本最高者），並在 `backends.toolchain.nvcc` 記錄實際路徑與找到它的方式。
The system SHALL look for `nvcc` not only on `PATH` but, in order, in `PATH`, `CUDA_HOME/bin`, `CUDA_PATH/bin`, `/usr/local/cuda/bin`, and `/usr/local/cuda-*/bin` (highest version wins), recording the actual path and how it was found in `backends.toolchain.nvcc`.

#### Scenario: CUDA 不在 PATH 中 / CUDA not on PATH

- **WHEN** `nvcc` 不在 `PATH`，但存在 `/usr/local/cuda-13.3/bin/nvcc`
  `nvcc` is not on `PATH`, but `/usr/local/cuda-13.3/bin/nvcc` exists
- **THEN** `backends.buildable.cuda.ok` 為 `true`（若驅動與編譯器也具備），且 `backends.toolchain.nvcc.found_via` 為 `standard_location`
  `backends.buildable.cuda.ok` is `true` (given a driver and a compiler), and `backends.toolchain.nvcc.found_via` is `standard_location`

#### Scenario: 完全沒有 CUDA toolkit / No CUDA toolkit at all

- **WHEN** 以上位置都找不到 `nvcc`
  `nvcc` is found in none of the locations above
- **THEN** `backends.buildable.cuda.ok` 為 `false`，`reason` 列出已檢查的位置
  `backends.buildable.cuda.ok` is `false`, and `reason` lists the locations checked

### Requirement: Path Independence

探測器的行為 SHALL 與目前工作目錄無關：專案根目錄由腳本自身位置推得，`.venv`、`build-*`、預設輸出位置都相對於專案根目錄。
The probe's behaviour SHALL NOT depend on the current working directory: the project root is derived from the script's own location, and `.venv`, `build-*`, and the default output location are all relative to that root.

#### Scenario: 從其他目錄執行 / Run from another directory

- **WHEN** 使用者在專案以外的目錄執行 `python /path/to/jiezi_LLM/scripts/hwprobe.py`
  The user runs `python /path/to/jiezi_LLM/scripts/hwprobe.py` from a directory outside the project
- **THEN** 仍能找到專案 `.venv` 中的 `cmake` / `ninja` 與 `build-*` 中的 binary，且預設寫入 `<專案根目錄>/facts.json`
  It still finds `cmake` / `ninja` in the project's `.venv` and binaries under `build-*`, and writes to `<project root>/facts.json` by default

### Requirement: Machine Fingerprint

`facts.json` SHALL 含 `fingerprint` 區塊（CPU 型號、實體核數、RAM 總量、GPU 名稱與 VRAM 總量、平台、驅動版本）及其雜湊值 `fingerprint.id`，供量測結果標示來源機器（規則 R21.6）。
`facts.json` SHALL include a `fingerprint` block (CPU model, physical core count, total RAM, GPU names and total VRAM, platform, driver version) and its hash `fingerprint.id`, so measurements can name their source machine (rule R21.6).

#### Scenario: 同一台機器重複探測 / Re-probing the same machine

- **WHEN** 在同一台機器上探測兩次，且期間只有可用記憶體等動態數值改變
  The same machine is probed twice, with only dynamic values such as free memory changing in between
- **THEN** 兩次的 `fingerprint.id` 相同
  Both runs produce the same `fingerprint.id`

#### Scenario: 換一台機器 / A different machine

- **WHEN** CPU 型號、RAM 總量或 GPU 任一項不同
  The CPU model, total RAM, or GPU differs
- **THEN** `fingerprint.id` 不同
  `fingerprint.id` differs

### Requirement: Graceful Degradation Off Linux

在非 Linux 平台（例如 macOS）執行時，依賴 `/proc`、`/sys`、`/dev` 的探測 SHALL 回報 `present: false` 與 `reason`，而不是中斷程式（規則 R21.2）。
On non-Linux platforms (e.g. macOS), probes that rely on `/proc`, `/sys`, or `/dev` SHALL report `present: false` with a `reason` instead of aborting (rule R21.2).

#### Scenario: 在 macOS 上執行 / Running on macOS

- **WHEN** 在沒有 `/proc/cpuinfo` 的平台執行探測器
  The probe runs on a platform without `/proc/cpuinfo`
- **THEN** `cpu.present` 為 `false` 並附 `reason`，程式仍輸出完整的 JSON 結構，exit code 為 0
  `cpu.present` is `false` with a `reason`, the program still writes the complete JSON structure, and the exit code is 0

### Requirement: No Side Effects

探測器 SHALL 不修改系統狀態、不安裝套件、不寫入 `--out` 指定路徑以外的檔案。
The probe SHALL NOT modify system state, install packages, or write any file other than the `--out` path.

#### Scenario: 唯讀保證 / Read-only guarantee

- **WHEN** 探測器執行完成
  The probe finishes
- **THEN** 除輸出檔外，專案與系統皆無變更
  Apart from the output file, neither the project nor the system has changed

### Requirement: Resource Reservation

探測器 SHALL 輸出 `budgets` 區塊，明列每個資源的保留量與可用量，確保任何工作都不會占盡硬體（規則 R18.1）。
The probe SHALL output a `budgets` block stating the reserved and usable amount of every resource, so no workload can consume all hardware (rule R18.1).

#### Scenario: CPU 保留實體核 / CPU reserves physical cores

- **WHEN** 系統有 14 個實體核且 policy 保留 2 核
  The system has 14 physical cores and the policy reserves 2
- **THEN** `budgets.cpu.usable_threads` 為 12，且 `affinity_hint` 恰含 12 個邏輯 CPU、分屬 12 個不同的實體核，並排除被保留的核
  `budgets.cpu.usable_threads` is 12, and `affinity_hint` contains exactly 12 logical CPUs on 12 distinct physical cores, excluding the reserved ones

#### Scenario: 親和性依實際拓撲推導 / Affinity derived from the real topology

- **WHEN** 邏輯 CPU 2k 與 2k+1 同屬實體核 k
  Logical CPUs 2k and 2k+1 belong to physical core k
- **THEN** `affinity_hint` SHALL 每核只取一個邏輯 CPU（例：`4,6,…,26`），MUST NOT 以連號 `0-(n-1)` 假設邏輯編號等於核心編號
  `affinity_hint` SHALL take one logical CPU per core (e.g. `4,6,…,26`) and MUST NOT assume logical ids equal core ids via a contiguous `0-(n-1)`

#### Scenario: 拓撲不可得 / Topology unavailable

- **WHEN** 無法取得「實體核 → 邏輯 CPU」對應
  The physical-core-to-logical-CPU mapping is unavailable
- **THEN** `affinity_hint` 為 `null` 並附 `affinity_reason`，不得猜測
  `affinity_hint` is `null` with an `affinity_reason`; it MUST NOT guess

#### Scenario: RAM 雙重上限 / RAM dual cap

- **WHEN** 可用 RAM 為 17158 MiB、floor 為 2560 MiB、fraction 為 0.70
  Available RAM is 17158 MiB, the floor is 2560 MiB, and the fraction is 0.70
- **THEN** `usable_mib` 取 `min(12010, 14598)` = 12010，且 `binding_constraint` 為 `fraction`
  `usable_mib` is `min(12010, 14598)` = 12010, and `binding_constraint` is `fraction`

#### Scenario: 可用量低於底線 / Available below the floor

- **WHEN** 可用 RAM 低於 floor
  Available RAM is below the floor
- **THEN** `usable_mib` 為 0（不得為負），`binding_constraint` 為 `floor`
  `usable_mib` is 0 (never negative), and `binding_constraint` is `floor`

#### Scenario: 無 GPU / No GPU

- **WHEN** 系統沒有 GPU
  The system has no GPU
- **THEN** `budgets.vram` 為 `null` 而非 `0`（區分「沒有裝置」與「額度為零」）
  `budgets.vram` is `null`, not `0` (distinguishing "no device" from "zero allowance")

#### Scenario: 保留策略可稽核 / Auditable reservation policy

- **WHEN** 讀取 `facts.json`
  `facts.json` is read
- **THEN** `budgets.policy` 完整列出所有常數（`cpu_reserve_cores`、`ram_floor_mib`、`ram_max_fraction_of_available`、`vram_floor_mib`、`vram_max_fraction_of_free`、`max_age_seconds`），下游不得另行寫死
  `budgets.policy` lists every constant (`cpu_reserve_cores`, `ram_floor_mib`, `ram_max_fraction_of_available`, `vram_floor_mib`, `vram_max_fraction_of_free`, `max_age_seconds`), and downstream code MUST NOT hardcode them

#### Scenario: WSL2 拓撲註記 / WSL2 topology note

- **WHEN** 在 WSL2 上執行
  Running on WSL2
- **THEN** `budgets.cpu.topology_note` 說明 vCPU 不固定對應實體核、核心保留只是近似（規則 R17.4）
  `budgets.cpu.topology_note` states that vCPUs are not pinned to host cores and core reservation is approximate (rule R17.4)
