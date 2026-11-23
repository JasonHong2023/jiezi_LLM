## 1. 上限單一來源 / Limits single source

- [x] 1.1 新增 `src/jiezi/agent/limits.py`，定義不可變 `EFFECTIVE_LIMITS` 六個鍵值 / Add `src/jiezi/agent/limits.py` with immutable `EFFECTIVE_LIMITS` for six keys
- [x] 1.2 讓 `src/jiezi/agent/loop.py` 與 `src/jiezi/agent/contract.py` 改為讀取 `limits.py`，保留既有常數名稱 / Make `loop.py` and `contract.py` consume `limits.py` while keeping legacy constant names
- [x] 1.3 在 `tests/test_agent_hardening.py` 驗證三處上限一致且 `EFFECTIVE_LIMITS` 不可變 / Verify limit parity and immutability in `tests/test_agent_hardening.py`

## 2. 合成語料清單 / Synthetic corpus manifest

- [x] 2.1 建立 `tests/fixtures/agent_redteam/manifest.json`，含版本、五個分類與合成案例 / Create `tests/fixtures/agent_redteam/manifest.json` with version, five categories, and synthetic cases
- [x] 2.2 在 `tests/test_agent_hardening.py` 加入清單載入與欄位驗證 / Add manifest loading and field validation in `tests/test_agent_hardening.py`
- [x] 2.3 驗證缺少分類、重複 `id` 或未標記機密字串會失敗 / Verify missing category, duplicate `id`, or unmarked secret string fails

## 3. 代理迴圈與授權回歸 / Agent loop and grant regressions

- [x] 3.1 以 `FakeMcp` 補重複呼叫略過、逾時 fail closed、結果截斷與舊結果縮短測試 / Add skipped repeated calls, timeout fail-closed, result truncation, and old-result shrink tests with `FakeMcp`
- [x] 3.2 補 revoke-after-grant、symlink 逃逸、secret deny 與稽核無內容測試 / Add revoke-after-grant, symlink escape, secret deny, and content-free audit tests
- [x] 3.3 保留並標記真實子行程取消 ≤ 1 秒測試為回歸關卡 / Keep and mark the real child cancellation ≤ 1 second test as a gate

## 4. 多來源注入回歸 / Multi-source injection regression

- [x] 4.1 在語料補 web/document/memory/skill 注入案例與各來源正常對照 / Add web/document/memory/skill injection cases and benign controls to the corpus
- [x] 4.2 在 `tests/test_injection.py` 用語料驗證句型命中、來源位置與正常對照不誤報 / Use the corpus in `tests/test_injection.py` to verify pattern hits, locations, and benign controls
- [x] 4.3 驗證使用者本人文字不被掃描，且標記請求不進技能或記憶 / Verify the user's own text is not scanned and flagged requests do not enter skills or memory

## 5. Budget 與稽核對齊 / Budget and audit alignment

- [x] 5.1 在 `tests/test_agent_hardening.py` 驗證 contract `effective_budget` 等於 `EFFECTIVE_LIMITS` / Verify contract `effective_budget` equals `EFFECTIVE_LIMITS` in `tests/test_agent_hardening.py`
- [x] 5.2 在 `tests/test_agent_hardening.py` 搜尋稽核檔，確認沒有注入句、檔案內容或機密值 / Search audit files in `tests/test_agent_hardening.py` for injection text, file content, or secrets

## 6. 驗證與紀錄 / Validation and records

- [x] 6.1 執行 `openspec validate add-agent-hardening --strict`、`openspec validate --all --strict` 與 `GIT_MASTER=1 git diff --check` / Run strict change validation, strict all-spec validation, and diff check
- [x] 6.2 執行 `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`，確認不少於 711 項且全過 / Run the full unittest suite and confirm at least 711 tests pass
- [x] 6.3 依 R19.4 更新 `docs/dev-plan.md` §15.7、`HANDOFF.md` 與 `2026-11-20.md`，記錄結果與殘留風險 / Update `docs/dev-plan.md` §15.7, `HANDOFF.md`, and `2026-11-20.md` with results and residual risks per R19.4

## 7. 核准關卡 / Approval gate

- [x] 7.1 向使用者報告驗證結果並等待「可以實作」；未核准前不 `/opsx-apply` / Report validation results and wait for "ready to implement"; do not `/opsx-apply` before approval
