# tools Specification

## Purpose
TBD - created by archiving change add-tools. Update Purpose after archive.
## Requirements
### Requirement: Computed Facts

問題含算式、單位換算或日期計算時，gateway SHALL 由程式算出結果附給模型，並 SHALL 在回答後附上計算結果；計算 SHALL NOT 使用 eval，且 SHALL 不把模型名稱、日期、電話號碼當成算式。
For arithmetic, unit or date questions the gateway SHALL compute the result in code, attach it, and append it after the answer; it SHALL NOT use eval and SHALL NOT treat model names, dates or phone numbers as expressions.

#### Scenario: 算錯的題目 / A wrong claim

- **WHEN** 使用者問「1+3=2 多少?」
  The user asks "1+3=2 多少?"
- **THEN** 模型收到「1+3 = 4（題目寫的 2 不正確）」
  The model receives that 1+3 is 4 and the claim of 2 is wrong

#### Scenario: 模型算錯 / The model errs

- **WHEN** 問「2^10 是多少」，本機模型回答 2048
  The local model answers 2048 to 2^10
- **THEN** 答案查核不通過，本機帶著錯誤說明重答
  The grounded check fails and the model retries

#### Scenario: 不是算式 / Not an expression

- **WHEN** 使用者問「Qwen3.5-2B 是什麼」或提到電話「0912-345-678」
  The user mentions a model name or a phone number
- **THEN** 不附計算結果
  No computed facts are attached

