## 1. 登錄表資料 / Registry data

- [ ] 1.1 建立 `docs/capabilities.toml`，填入 5 個已完成 change 的完整記錄（add-agent-contract、add-agent-hardening、add-scrapling-web-read、add-client-tool-filter、add-holiday-tool），缺項以 "unknown" 標註並在報告列出。

## 2. 核心模組 / Core module

- [ ] 2.1 新增 `src/jiezi/capabilities.py`，實作 `load()`、`validate()`、`check_proposals()`。
- [ ] 2.2 單元測試覆蓋：正常載入、缺檔、壞 TOML、驗證各規則（缺欄位、kind 錯誤、existing_solutions 空無理由、security_scan issues+enabled 衝突、重複 id）、`check_proposals()` 缺項偵測。

## 3. CLI 子命令 / CLI subcommand

- [ ] 3.1 新增 `src/jiezi/cli/capabilities.py`，實作 `jiezi capabilities check` 子命令。
- [ ] 3.2 修改 `src/jiezi/cli/__init__.py` 註冊 capabilities 子命令群組。
- [ ] 3.3 CLI 測試：正常輸出、錯誤輸出、退出碼 0/1、參數覆蓋預設路徑。

## 4. 規格 / Specs

- [ ] 4.1 新增 `openspec/changes/add-agent-capability-registry/specs/agent-capability-registry/spec.md`，定義 ADDED requirements（含 SHALL/MUST 與至少一個 Scenario WHEN/THEN）。

## 5. 驗證與紀錄 / Validation and records

- [ ] 5.1 執行 `openspec validate add-agent-capability-registry --strict`、`openspec validate --all --strict` 與 `GIT_MASTER=1 git diff --check`。
- [ ] 5.2 執行 `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`，確認全量測試通過（不少於現有測試數）。
- [ ] 5.3 依 R19.4 更新相關紀錄文件（如有），記錄驗證結果與殘留風險。
- [ ] 5.4 撰寫 `WORKER_REPORT.md` 總結改動檔案、驗證指令與結果數字、未完成項與疑點。

## 完成標準 / Done Criteria

- `openspec validate add-agent-capability-registry --strict` 通過
- `openspec validate --all --strict` 通過
- 全量 unittest 全部通過（基準 ≥ 711）
- `GIT_MASTER=1 git diff --check` 無輸出
- `jiezi capabilities check` 正常輸出且退出碼 0
- `docs/capabilities.toml` 含 5 筆完整記錄
- `src/jiezi/capabilities.py`、`src/jiezi/cli/capabilities.py`、`tests/test_capabilities.py` 存在並通過測試