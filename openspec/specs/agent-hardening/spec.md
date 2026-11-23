# agent-hardening Specification

## Purpose
TBD - created by archiving change add-agent-hardening. Update Purpose after archive.
## Requirements
### Requirement: Versioned synthetic red-team corpus / 版本化合成紅隊語料

系統 SHALL 在 `tests/fixtures/agent_redteam/manifest.json` 維護版本化語料清單，並 SHALL 以 `schema_version`、`categories`、`cases` 描述每筆案例；語料 SHALL 全為合成資料，SHALL NOT 含真實金鑰、`.env`、`facts.json`、模型權重或使用者機密。 / The system SHALL maintain a versioned manifest at `tests/fixtures/agent_redteam/manifest.json` with `schema_version`, `categories`, and `cases`; every fixture SHALL be synthetic and SHALL NOT contain a real key, `.env`, `facts.json`, model weight, or user secret.

語料清單 SHALL 至少包含 `loop_limits`、`cancellation`、`grants`、`injection`、`budget_alignment` 五個分類；每筆案例 SHALL 有 `id`、`category`、`input`、`expected` 與 `synthetic: true`。 / The manifest SHALL contain at least the five categories `loop_limits`, `cancellation`, `grants`, `injection`, and `budget_alignment`; every case SHALL have `id`, `category`, `input`, `expected`, and `synthetic: true`.

#### Scenario: 語料清單可讀且分類完整 / Manifest loads with complete categories

- **WHEN** 測試載入 `manifest.json` 且 `schema_version` 為支援版本。 / **WHEN** the test loads `manifest.json` with a supported `schema_version`.
- **THEN** 五個必要分類都存在，且每筆案例都有唯一 `id` 與 `synthetic: true`。 / **THEN** all five required categories exist and every case has a unique `id` and `synthetic: true`.

#### Scenario: 未標記的機密字串被拒 / Unmarked secret-like string is rejected

- **WHEN** 案例文字含 `sk-` 開頭的長字串或真實憑證標記，但沒有 `synthetic: true` 或保留範例網域。 / **WHEN** a case contains a long `sk-` token or a real credential marker without `synthetic: true` or a reserved example domain.
- **THEN** 語料驗證失敗，並指出案例 `id`。 / **THEN** corpus validation fails and names the case `id`.

### Requirement: Agent hardening regression gate / 代理強化回歸關卡

強化回歸 SHALL 執行語料清單中的全部案例，並 SHALL 在任一案例失敗、分類缺失或基線退化時失敗。 / The hardening regression SHALL execute every manifest case and SHALL fail on any case failure, missing category, or baseline regression.

基線 SHALL 至少維持目前 711 項測試、`docs/dev-plan.md` 原 642 項、唯讀代理 6/6、中止 ≤ 1 秒與紅隊案例全過。 / The gate SHALL preserve at least the current 711 tests, the original 642 tests in `docs/dev-plan.md`, read-only agent 6/6, stop within 1 second, and all red-team cases passing.

#### Scenario: 全部案例通過 / All cases pass

- **WHEN** 語料案例、既有測試與 ≥ 711 項全量測試都通過。 / **WHEN** corpus cases, existing tests, and the full suite of at least 711 tests all pass.
- **THEN** 回歸關卡為通過。 / **THEN** the regression gate is green.

#### Scenario: 分類缺失或案例失敗 / Missing category or failed case

- **WHEN** 語料清單缺少必要分類，或任一案例的預期結果不符。 / **WHEN** a required category is absent from the manifest or any case result differs from `expected`.
- **THEN** 回歸關卡失敗並列出失敗案例 `id`。 / **THEN** the gate fails and lists the failing case `id`.

#### Scenario: 中止超過一秒 / Stop exceeds one second

- **WHEN** 真實子行程取消測試量到中止時間大於 1 秒。 / **WHEN** the real child cancellation test measures stop time greater than 1 second.
- **THEN** 回歸關卡失敗。 / **THEN** the regression gate fails.

### Requirement: Effective limits single source / 有效上限單一來源

`src/jiezi/agent/limits.py` SHALL 提供不可變的 `EFFECTIVE_LIMITS` 映射，鍵與值 SHALL 固定為 `max_steps=6`、`max_calls_per_step=3`、`result_chars=2500`、`old_result_chars=400`、`tools_budget=2600`、`call_timeout_s=120`。 / `src/jiezi/agent/limits.py` SHALL expose an immutable `EFFECTIVE_LIMITS` mapping with exactly `max_steps=6`, `max_calls_per_step=3`, `result_chars=2500`, `old_result_chars=400`, `tools_budget=2600`, and `call_timeout_s=120`.

`loop.py` 與 `contract.py` SHALL 從該映射取得上限常數，SHALL NOT 各自重新定義數值，且 fail-closed 語意 SHALL 不變。 / `loop.py` and `contract.py` SHALL derive their limit constants from that mapping, SHALL NOT redefine values, and SHALL preserve fail-closed semantics.

#### Scenario: 上限值一致 / Limit values agree

- **WHEN** 測試比較 `limits.EFFECTIVE_LIMITS`、`contract.CEILINGS` 與 `loop.py` 的常數。 / **WHEN** a test compares `limits.EFFECTIVE_LIMITS`, `contract.CEILINGS`, and the constants in `loop.py`.
- **THEN** 六個鍵的值完全相同。 / **THEN** all six keys have identical values.

#### Scenario: 上限映射不可變 / Limit mapping is immutable

- **WHEN** 測試嘗試修改 `EFFECTIVE_LIMITS` 的任一鍵。 / **WHEN** a test attempts to modify any key of `EFFECTIVE_LIMITS`.
- **THEN** 修改被拒絕，原值不變。 / **THEN** the mutation is rejected and the original value is unchanged.

