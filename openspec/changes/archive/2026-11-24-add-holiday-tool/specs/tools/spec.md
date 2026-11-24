## ADDED Requirements

### Requirement: Holiday Calendar
When a question asks about Taiwan's public holidays, long weekends or make-up days for a year, the system SHALL compute that year's holidays from the articles of the Memorial Days and Holidays Implementation Act in the local law database — dates, weekdays, lunar festivals converted to the solar calendar, and make-up days estimated by the usual rule and marked as subject to the official announcement — and SHALL attach them as computed facts with the statute articles as the source.

#### Scenario: 2027 年的國定假日 / Holidays in 2027
- **WHEN** 使用者問「台灣2027年的國定假日有哪些?」
  The user asks for 2027's public holidays
- **THEN** 本機依附上的計算結果回答（含除夕 2027-02-05 與春節連假），回答後附【計算】與條例第 4、6、8 條，不請教 Claude
  The local model answers from the computed list with the statute as the source, without consulting Claude
