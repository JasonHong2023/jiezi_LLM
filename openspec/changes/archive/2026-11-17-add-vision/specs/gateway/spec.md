## ADDED Requirements

### Requirement: Image Input

核心模型有視覺模組時，gateway SHALL 把 OpenAI 格式的圖片內容原樣送給本機引擎，並 SHALL 以訊息的文字部分查資料；核心沒有視覺模組時 SHALL NOT 把圖片問題交給本機模型，而是轉給可用的雲端模型或回 400 並說明原因。
With a vision core the gateway SHALL pass image content to the local engine and ground on the text parts; without one it SHALL NOT send image questions to the local model, using the cloud or returning 400.

#### Scenario: 文字核心收到圖片 / A text-only core gets an image

- **WHEN** 核心沒有視覺模組、雲端未開啟，使用者以 jiezi-local 傳圖片
  The core is text-only, the cloud is off, and an image arrives
- **THEN** 回 400（vision_unavailable），本機模型不被呼叫
  It returns 400 and the local model is not called
