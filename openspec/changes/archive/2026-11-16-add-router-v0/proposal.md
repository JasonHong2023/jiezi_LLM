## Why

開發計畫 4.5 路由器。學習式路由器需要足夠的軌跡資料，目前還不夠；先用規則版：本機一定答不了的問題（要上網、即時資料）在 `jiezi` 策略下直接轉交，省下一次本機生成與等待。缺口報告中這類問題佔 3/20。
Learned routing needs more trajectories; a rule-based v0 sends web/live questions straight to escalation.

## What Changes

- `jiezi` 策略下，問題含網址、天氣、新聞、股價、匯率、「上網查」等且沒有程式算好或記憶中的答案時，跳過本機直接轉交（原因 `needs_web`）。
  Under `jiezi`, web/live questions without computed or remembered answers skip the local model (`needs_web`).
- 判斷用比記憶 `WEB` 更嚴格的 `LIVE` 規則：「我今天心情不好」照常由本機回答，「今天星期幾」由程式算好後本機回答。
  A stricter rule than memory's WEB keeps chat and computed questions local.

## Non-Goals

- 學習式路由（RouteLLM 式），等軌跡資料足夠後再做。/ Learned routing, later.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `escalation`：新增事前路由。/ Adds pre-routing.

## Impact

- 只影響 `jiezi` 策略；`jiezi-local` 不受影響。/ Only the `jiezi` policy.
