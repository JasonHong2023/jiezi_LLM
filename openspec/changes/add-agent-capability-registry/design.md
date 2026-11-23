## Architecture / 架構

### Data Model / 資料模型

`docs/capabilities.toml` 為 TOML 格式陣列，每個元素為一個 capability 記錄：

```toml
[[capabilities]]
id = "agent-contract"                    # 唯一識別碼，對應 change 名稱去前綴
name = "Agent Contract"                  # 顯示名稱
kind = "core"                            # "skill" | "mcp" | "core"
change = "add-agent-contract"            # openspec change 目錄名
existing_solutions = "MCP spec, Anthropic Skills, OWASP LLM Top 10 2025, OWASP Agent Security Cheat Sheet (dev-plan §15.3); reuse bounded loop and least privilege, no new dependency"
security_scan = "2026-11-19 ok (no new dependency, port, permission, secret handling; residual risk: contract text treated as trusted instruction, mitigated by metadata-only and injection guard)"
version = "1.0.0"
owner = "JasonHong"
removal_condition = "If core loop migrates to non-contract architecture, remove contract.py and related tests"
status = "enabled"                       # "enabled" | "disabled" | "deprecated"
```

**選擇 TOML 而非 JSON 的理由**：
1. TOML 支援多行字串與註解，適合人工維護長文欄位（`existing_solutions`、`security_scan`、`removal_condition`）。
2. Python 3.11+ 內建 `tomllib`，零外部相依，符合「只用標準函式庫」要求。
3. 陣列語法 `[[capabilities]]` 自然對應多筆記錄，比 JSON 陣列更易閱讀與編輯。

### Module Structure / 模組結構

```
src/jiezi/
├── capabilities.py      # 核心邏輯：load(), validate(), check_proposals()
└── cli/
    ├── __init__.py      # 註冊 capabilities 子命令群組
    └── capabilities.py  # CLI 介面：jiezi capabilities check
```

### Key Functions / 關鍵函式

#### `load(path: Path | str = "docs/capabilities.toml") -> list[dict]`
- 讀取並解析 TOML，回傳能力記錄列表。
- 檔案不存在 → 拋 `FileNotFoundError`。
- 解析失敗 → 拋 `tomllib.TOMLDecodeError`（繼承自 `ValueError`）。

#### `validate(capabilities: list[dict]) -> list[str]`
- 對每筆記錄執行驗證，回傳錯誤訊息列表（空列表 = 全部通過）。
- 驗證規則：
  1. **必要欄位齊全**：`id`、`name`、`kind`、`change`、`existing_solutions`、`security_scan`、`version`、`owner`、`removal_condition`、`status`。
  2. **kind 合法**：只能是 `"skill"`、`"mcp"`、`"core"`。
  3. **existing_solutions 非空或有理由**：若為空字串或僅含空白，且不含「無，理由：」或「none, reason:」→ 錯誤。
  4. **security_scan 結構**：需含日期（YYYY-MM-DD）與結論（`ok` 或 `issues`），格式彈性但至少可用 regex 擷取。
  5. **status 與 security_scan 一致性**：若 `security_scan` 結論為 `issues` 但 `status == "enabled"` → 錯誤。
  6. **id 唯一**：全表 `id` 不重複。

#### `check_proposals(root: Path | str = "openspec/changes") -> dict[str, list[str]]`
- 掃描 `root` 下每個子目錄（排除 `archive/`）。
- 讀取各目錄的 `proposal.md`，檢查是否含有三個必要段落（標題不分大小寫）：
  - 分類：`## Classification` 或 `## 分類` 或內文含「分類：」／「Classification:」
  - 現成方案：`## Existing-solution search` 或 `## 現成方案搜尋` 或內文含「現成方案」／「Existing solution」
  - 資安掃描：`## Security scan` 或 `## 資安掃描` 或內文含「資安掃描」／「Security scan」
- 回傳 `{change_name: [missing_section_names]}`，僅包含有缺項的 change。

### CLI Design / CLI 設計

```
jiezi capabilities check [--toml PATH] [--changes-root PATH]
```

- `--toml`：指定 capabilities.toml 路徑（預設 `docs/capabilities.toml`）。
- `--changes-root`：指定 changes 根目錄（預設 `openspec/changes`）。
- 輸出：先印 capabilities 驗證結果（通過／失敗細節），再印 proposal 三段檢查結果（缺項清單）。
- 退出碼：0 = 全通過；1 = 有驗證錯誤或缺項。

### Integration with Existing CLI / 與既有 CLI 整合

`src/jiezi/cli/__init__.py` 現為空殼，需改為命令註冊入口。參考 `add-cli` 設計（`src/jiezi/cli/check.py` 獨立檔案、`__init__.py` 導出 `main`），`capabilities` 子命令群組同樣採用獨立檔案 `capabilities.py`，在 `__init__.py` 中掛載。

### Error Handling / 錯誤處理

- 所有驗證錯誤以列表回傳，不拋例外（除了 `load()` 的 IO/解析錯誤）。
- CLI 層統一捕獲例外並轉為非零退出碼與 stderr 訊息。
- 不使用 `sys.exit()` 在核心函式中，只在 CLI `main()` 返回碼。

### Open Questions / 未決問題

無。所有設計決策已在 proposal 階段確認。

## Test Strategy / 測試策略

| 測試檔 | 覆蓋項目 |
|---|---|
| `tests/test_capabilities.py` | `load()` 正常/缺檔/壞檔、`validate()` 各規則、`check_proposals()` 缺項偵測、CLI 輸出與退出碼 |
| `tests/fixtures/capabilities/` | 測試用 TOML（合法、缺欄位、kind 錯誤、security_scan issues+enabled 衝突、重複 id） |

測試不依賴網路、GPU、雲端金鑰；僅讀取本機檔案。

## Security Considerations / 安全考量

- `capabilities.toml` 為本機靜態文件，不接受外部輸入，無注入面。
- `check_proposals()` 唯讀掃描 `openspec/changes/`，不執行任何程式碼。
- CLI 僅輸出，不寫入任何檔案。
- 建議：將 `docs/capabilities.toml` 納入 git 版控，變更可追溯。