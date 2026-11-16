"""Phase 6 自我進化的訓練工具（add-sft-training；規則 R20）。
Training tools for Phase 6 self-evolution (add-sft-training; rule R20).

- config：訓練設定與顯示記憶體估算 / settings and VRAM estimate
- gate：回歸關卡（R20.1、R20.6），不需要 PyTorch / regression gate, no PyTorch needed
- sft：LoRA SFT（需要 torch、transformers、peft，執行時才載入）/ LoRA SFT, heavy imports at run time
- export：合併 LoRA、轉 GGUF、量化 / merge, convert to GGUF, quantize
"""
