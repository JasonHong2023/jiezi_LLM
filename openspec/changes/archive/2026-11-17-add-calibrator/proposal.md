## Why

開發計畫 4.4 calibrator。supervisor 的擺放規則只有「整個模型上 GPU，否則純 CPU」；放不進整張顯卡的模型（例如 4B Q8_0、9B），部分層上 GPU 可能比純 CPU 快，需要在這台電腦實測。
The supervisor only knows whole-GPU or CPU; partial offload must be measured on this machine.

## What Changes

- `scripts/jiezi calibrate [--model]`：用鎖定版本的 llama-bench，在資源預算下量 `-ngl` 0／8／16／24／全部的提示與生成速度，寫進 `var/runtime/bench.json`（記錄 SHA-256）。
  Measure several -ngl values with the pinned llama-bench and record them with the file's SHA-256.
- supervisor：預設擺放為純 CPU、且同一個檔案（SHA-256 相同）有實測最佳 ngl 時，改用該 ngl（擺放標為 partial）。
  The supervisor adopts the measured ngl for a CPU-placed core when the file matches.

## Non-Goals

- Dovetail 拓撲（大模型在 CPU、小模型在 GPU 做推測解碼）：需要選定核心與草稿模型，之後評估。
  The Dovetail topology, later.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `supervisor`：採用實測的部分擺放。/ Uses measured partial offload.

## Impact

- 重度工作（GPU），排在 E0 之後執行。/ Heavy; scheduled after E0.
