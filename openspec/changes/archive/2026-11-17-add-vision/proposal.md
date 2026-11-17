## Why

使用者 2026-11-16 問「這模型有加入視覺功能嗎？」。目前核心 Qwen3-0.6B 只有文字；但 E0 候選的 Qwen3.5（0.8B／2B／4B）是原生多模態（image-text-to-text），unsloth 的 GGUF 附有 mmproj 視覺投影器，鎖定的 llama.cpp 支援 `--mmproj`。先把支援做好，G1 選定 Qwen3.5 後下載對應的 mmproj 即可看圖。
The current core is text-only, but the Qwen3.5 candidates are natively multimodal with mmproj files; support is built now and enabled when G1 picks one.

## What Changes

- 模型清單：Qwen3.5 0.8B／2B／4B 的 mmproj-F16（鎖定同一 commit 與 SHA-256，Apache-2.0）；核心條目以 `mmproj` 欄位指向它；檔案存在時引擎加 `--mmproj`。
  Manifest entries for the projectors; cores point to them; the engine gets --mmproj when the file exists.
- gateway：接受 OpenAI 格式的圖片內容；核心有視覺時原樣送入本機，並以文字部分查資料；核心沒有視覺時，有雲端就轉雲端，否則回 400（不讓文字模型對著看不到的圖亂答）；請教 Claude 的管道只收文字，帶圖時同樣處理。請求上限 1 MB → 8 MB。
  Image content is passed to a vision core; otherwise cloud or a clear 400.
- 上下文估算：每張圖以 400 token 估計，不把 base64 長度算進去。/ Images count 400 tokens each.
- `jiezi chat`：`/image 路徑`（png／jpg／webp／gif，≤ 5 MB）；只有最新一則保留圖片，歷史不存圖片。
  `/image` in chat; only the newest message keeps its image.
- `scripts/jiezi doctor` 顯示核心是否有視覺模組。

## Non-Goals

- 圖片進訓練資料。/ Images in training data.
- 截圖、螢幕理解（Phase 8 的唯讀工具）。/ Screen capture (Phase 8).

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `gateway`：新增圖片輸入。/ Adds image input.

## Impact

- mmproj 大小：0.8B 205 MB、2B 668 MB、4B 672 MB（G1 後只下載選定的那一個）。
