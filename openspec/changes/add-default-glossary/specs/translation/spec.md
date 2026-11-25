## ADDED Requirements

### Requirement: Built-In Agency Glossary / 內建機關英文名詞表
中翻英時系統 SHALL 自動套用隨程式發佈的台灣機關英文名詞表，只套用原文中出現的詞，並沿用既有的詞彙表檢查；使用者提供的詞彙表同詞時 SHALL 以使用者為準。詞表每一筆 SHALL 附來源網址。使用者 SHALL 能以 CLI `--no-default-glossary` 或 HTTP 選項 `jiezi_glossary_default: false` 關閉。翻譯結果的資訊 SHALL 列出這次套用的內建詞。
Chinese → English translation SHALL apply a shipped glossary of Taiwan agency names (only terms present in the source, each row with its source URL); the user's glossary SHALL win, and the built-in list SHALL be switchable off.

#### Scenario: 機關名照正式英文名 / Agency name uses the official English name

- **WHEN** 中翻英的原文含「經濟部」，使用者沒有提供詞彙表
  The source contains 經濟部 and the user gives no glossary
- **THEN** 提示要求譯為 Ministry of Economic Affairs，譯文沒有這個譯名時該段視為未通過並重試一次
  The prompt requires "Ministry of Economic Affairs" and a chunk without it fails the check and is retried once

#### Scenario: 使用者詞表優先 / The user's glossary wins

- **WHEN** 使用者的詞彙表把「經濟部」指定為 MOEA
  The user's glossary maps 經濟部 to MOEA
- **THEN** 使用 MOEA，不使用內建譯名
  MOEA is used instead of the built-in name

#### Scenario: 關閉內建詞表 / Built-in glossary off

- **WHEN** 使用者加上 `--no-default-glossary`
  The user passes `--no-default-glossary`
- **THEN** 只套用使用者的詞彙表（若有），資訊欄不列內建詞
  Only the user's glossary applies and no built-in terms are listed
