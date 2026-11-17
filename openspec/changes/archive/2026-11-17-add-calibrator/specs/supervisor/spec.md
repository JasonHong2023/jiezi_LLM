## ADDED Requirements

### Requirement: Measured Partial Offload

核心模型依預算判定為純 CPU、且 `bench.json` 有同一檔案（SHA-256 相同）的實測最佳 GPU 層數時，supervisor SHALL 以該層數載入；檔案不同時 SHALL NOT 採用。
A CPU-placed core with a measured best layer count for the same file SHALL load with it; a different file SHALL NOT use it.

#### Scenario: 換了檔案 / A different file

- **WHEN** bench.json 的 SHA-256 與核心檔案不同
  The recorded SHA-256 differs from the core file
- **THEN** 不採用實測值，照預算擺放
  The measurement is ignored
