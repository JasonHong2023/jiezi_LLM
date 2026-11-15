## 1. 來源與建置 / Sources and build

- [x] 1.1 `dictionaries/manifest.toml`、授權登記 `docs/licenses.md`（`moedict-revised`）/ Manifest and license registry
- [x] 1.2 `src/jiezi/dictionary.py`：下載與 SHA-256、建置 SQLite、查詢、詞語擷取 / Download, build, lookup, term extraction
- [x] 1.3 `scripts/jiezi dict build|lookup` / Commands

## 2. 對話整合 / Chat integration

- [x] 2.1 gateway：詞語問題時附上詞條原文與出處指示、`jiezi.sources`、`training_use: false` / Grounding, sources, training flag
- [x] 2.2 `.env.example`：`JIEZI_DICTIONARY` / Setting

## 3. 驗證 / Verification

- [x] 3.1 單元測試（觸發與不觸發、最長優先、SHA-256 不符、原文不變）；`openspec validate add-dictionary --strict` / Unit tests and validation
- [x] 3.2 實際建置並以 0.6B 測試幾個詞語問題 / Real build and a few word questions with the 0.6B
