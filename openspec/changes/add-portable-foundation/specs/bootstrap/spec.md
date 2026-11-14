# bootstrap Specification

## ADDED Requirements

### Requirement: One-Command Rebuild

系統 SHALL 提供 `scripts/bootstrap`，在乾淨的 Linux / WSL2 電腦上依序完成：檢查前置條件 → 建立 Python 環境 → 取得 llama.cpp → 執行 hwprobe → 建置後端 → 下載並驗證模型 → 冒煙測試（規則 R21.4）。
The system SHALL provide `scripts/bootstrap`, which on a clean Linux / WSL2 machine runs in order: prerequisite check → Python environment → llama.cpp → hwprobe → backend builds → model download and verification → smoke test (rule R21.4).

#### Scenario: 乾淨的電腦 / Clean machine

- **WHEN** 在只有 git、編譯器與網路的乾淨 Linux / WSL2 上 clone repo 後執行 `scripts/bootstrap`
  `scripts/bootstrap` runs right after cloning on a clean Linux / WSL2 machine that has only git, a compiler, and network access
- **THEN** 所有步驟完成，冒煙測試通過，且全程不需要修改任何程式或設定檔
  Every step completes, the smoke test passes, and no code or configuration file needs editing

#### Scenario: 重複執行 / Re-running

- **WHEN** 在已完成 bootstrap 的電腦上再次執行
  It runs again on a machine where bootstrap already completed
- **THEN** 已完成且仍有效的步驟被略過（例如模型 SHA-256 已吻合），不重複下載或重建
  Steps that are done and still valid are skipped (e.g. a model whose SHA-256 already matches); nothing is re-downloaded or rebuilt

#### Scenario: 中途失敗 / Failure midway

- **WHEN** 某個步驟失敗
  A step fails
- **THEN** 程式以非 0 結束，指出失敗的步驟與原因；修正後再次執行可從該步驟接續
  The program exits non-zero naming the failed step and its reason; after fixing, a re-run resumes from that step

### Requirement: Prerequisite Check

bootstrap SHALL 先檢查前置條件（git、C/C++ 編譯器、OpenSSL ≥ 3.0 開發標頭、uv、網路），缺少時列出每一項與對應平台的安裝方式後停止，不得自行安裝需要 sudo 的系統套件。
Bootstrap SHALL first check prerequisites (git, a C/C++ compiler, OpenSSL ≥ 3.0 development headers, uv, network) and, if any is missing, list each one with platform-specific install instructions and stop, never installing sudo-requiring system packages on its own.

#### Scenario: 缺少 uv / uv missing

- **WHEN** 系統找不到 `uv`
  `uv` is not found
- **THEN** bootstrap 顯示官方安裝方式並停止
  Bootstrap shows the official install method and stops

### Requirement: Environment Configuration

本機特有的設定 SHALL 只來自 `.env`（不進版控）；repo SHALL 提供 `.env.example` 列出每個變數、用途與範例值；`.env` 不存在時 bootstrap 由範本建立（規則 R21.3）。
Machine-specific settings SHALL come only from `.env` (not versioned); the repo SHALL ship `.env.example` listing every variable with its purpose and an example value; when `.env` is missing, bootstrap creates it from the template (rule R21.3).

#### Scenario: 未設定雲端 / No cloud configured

- **WHEN** `.env` 未設定 `JIEZI_CLOUD_BASE_URL`
  `.env` does not set `JIEZI_CLOUD_BASE_URL`
- **THEN** bootstrap 照常完成，並註明系統將以純本機模式運作
  Bootstrap still completes and notes that the system will run in local-only mode

#### Scenario: 機密不外洩 / Secrets stay local

- **WHEN** 檢查版控中的檔案
  The versioned files are inspected
- **THEN** 只有 `.env.example`（不含真實金鑰），`.env` 被 `.gitignore` 排除
  Only `.env.example` (with no real keys) exists; `.env` is excluded by `.gitignore`

### Requirement: Platform Setup Selection

需要 sudo 的平台步驟 SHALL 放在 `scripts/setup/<platform>/`，由偵測結果（原生 Ubuntu 或 WSL2）選擇；執行前 SHALL 列出將執行的內容並取得使用者同意；等待 sudo 密碼時 SHALL 沒有時間限制（逾時或輸入錯誤就回到等待狀態）（規則 R4、R15 C11）。
Sudo-requiring platform steps SHALL live in `scripts/setup/<platform>/` and be chosen from detection (native Ubuntu or WSL2); before running they SHALL list what will be done and obtain the user's consent; waiting for the sudo password SHALL have no time limit (on timeout or a wrong password it returns to waiting) (rules R4, R15 C11).

#### Scenario: WSL2 上安裝 CUDA toolkit / Installing the CUDA toolkit on WSL2

- **WHEN** 偵測到 WSL2、有 NVIDIA 驅動但沒有 CUDA toolkit，且使用者同意安裝
  WSL2 is detected with an NVIDIA driver but no CUDA toolkit, and the user agrees to install it
- **THEN** 使用 NVIDIA 的 `wsl-ubuntu` 套件庫，toolkit 版本依驅動支援的 CUDA 版本選擇，**不安裝驅動**；可開視窗時以新視窗等待輸入
  The NVIDIA `wsl-ubuntu` repository is used, the toolkit version follows the driver's supported CUDA version, and **no driver is installed**; a new window waits for input when one can be opened

#### Scenario: 原生 Ubuntu / Native Ubuntu

- **WHEN** 偵測到原生 Ubuntu
  Native Ubuntu is detected
- **THEN** 使用對應 Ubuntu 版本的 NVIDIA 套件庫（例如 `ubuntu2404`），其餘規則相同
  The NVIDIA repository for that Ubuntu release (e.g. `ubuntu2404`) is used; all other rules are the same

#### Scenario: 使用者拒絕或不支援的平台 / Declined or unsupported platform

- **WHEN** 使用者拒絕安裝，或平台不在支援清單
  The user declines, or the platform is unsupported
- **THEN** 該加速後端被略過並記錄原因，bootstrap 以純 CPU 繼續
  That accelerator backend is skipped with a recorded reason, and bootstrap continues CPU-only

### Requirement: Model Manifest

模型 SHALL 由 `models/manifest.toml` 定義，每筆必須含名稱、下載網址、SHA-256、大小、授權、是否允許商用、是否允許用於訓練、授權查證日期與來源；缺少授權欄位的模型 SHALL NOT 被下載（規則 R18.3）。
Models SHALL be defined in `models/manifest.toml`; each entry must have a name, download URL, SHA-256, size, license, commercial-use flag, training-use flag, license check date, and source; a model missing license fields SHALL NOT be downloaded (rule R18.3).

#### Scenario: 下載並驗證 / Download and verify

- **WHEN** 清單中的模型不存在於 `JIEZI_MODELS_DIR`
  A manifest model is absent from `JIEZI_MODELS_DIR`
- **THEN** 系統下載後驗證 SHA-256，不符就刪除該檔並報錯
  The system downloads it and verifies the SHA-256, deleting the file and failing on mismatch

#### Scenario: 缺少授權資訊 / Missing license information

- **WHEN** 某筆模型缺少授權相關欄位
  An entry lacks license fields
- **THEN** 系統拒絕下載該模型並指出缺少的欄位
  The system refuses to download it and names the missing fields

### Requirement: Smoke Test

bootstrap 的最後一步 SHALL 以**純 CPU、不連雲端**載入清單中標記為冒煙測試用的最小模型，回答一個固定問題，並在預算內完成（規則 R21、R18）。
The final bootstrap step SHALL load the manifest's designated smallest smoke-test model **CPU-only with no cloud**, answer a fixed question, and stay within budget (rules R21, R18).

#### Scenario: 冒煙測試通過 / Smoke test passes

- **WHEN** 冒煙測試執行
  The smoke test runs
- **THEN** 模型成功載入並產生非空回答，輸出所用的 build、模型、執行緒數與 t/s
  The model loads and produces a non-empty answer, and the build, model, thread count, and t/s are printed

### Requirement: Portability Guard

repo SHALL 包含一項不需要 GPU、網路或金鑰的自動檢查，掃描版控中的檔案，偵測使用者家目錄的絕對路徑、WSL distro 名稱、疑似金鑰，以及任何 PHP 檔案（規則 R6.13、R21.5、R23.1）。
The repo SHALL include an automated check, needing no GPU, network, or keys, that scans versioned files for absolute home-directory paths, WSL distro names, likely secrets, and any PHP files (rules R6.13, R21.5, R23.1).

#### Scenario: 發現寫死的路徑 / Hardcoded path found

- **WHEN** 某個版控檔案含 `/home/<實際使用者名稱>/` 形式的路徑
  A versioned file contains a path of the form `/home/<real username>/`
- **THEN** 檢查失敗並列出檔案與行號
  The check fails and lists the file and line

#### Scenario: 出現 PHP 檔案 / PHP file present

- **WHEN** repo 中出現 `*.php` 檔案
  A `*.php` file appears in the repo
- **THEN** 檢查失敗
  The check fails
