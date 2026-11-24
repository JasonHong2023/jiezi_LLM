## ADDED Requirements

### Requirement: Sound Effects From A Description / 依描述產生音效
系統 SHALL 在 `JIEZI_SFX=on` 時提供 `POST /v1/audio/sfx`，依文字描述（中文或英文）或 earshot 聲音編號在 CPU 上產生音效並回傳音檔，需要 gateway 金鑰。earshot SHALL 安裝在獨立 venv 並鎖定 commit，只裝基本相依，SHALL NOT 安裝會下載模型或連線雲端的額外套件。工作行程 SHALL 只能把檔案寫在 `var/sfx/out/` 內。回應 SHALL 告知選中的聲音編號。紀錄 SHALL 只記中繼資料。
With `JIEZI_SFX=on` the gateway SHALL make sound effects on the CPU from a description or a design id, using an isolated, pinned earshot install without model or cloud extras.

#### Scenario: 中文描述 / Chinese description

- **WHEN** 使用者以「下雨打在窗戶上，10 秒」要求音效
  The user asks for "rain on a window, 10 s" in Chinese
- **THEN** 系統把描述轉成英文交給 earshot，回傳約 10 秒的音檔，並在回應中標出選中的聲音編號
  The description is turned into English, a 10 s file is returned and the chosen design id is reported

#### Scenario: 超出輸出資料夾的路徑 / Path outside the output folder

- **WHEN** 工作行程收到 `var/sfx/out/` 以外的輸出路徑
  The worker receives an output path outside `var/sfx/out/`
- **THEN** 拒絕執行並回報錯誤，不寫任何檔案
  It refuses and writes nothing

#### Scenario: 未啟用 / Disabled

- **WHEN** `JIEZI_SFX` 未設為 on
  `JIEZI_SFX` is not on
- **THEN** 音效端點回應 404 並說明如何啟用
  The endpoint answers 404 with how to enable it

### Requirement: Ambience Under Read-Aloud / 朗讀加背景音效
`/v1/audio/speech` SHALL 接受選填的 `jiezi_background`（內建環境聲名稱）與 `jiezi_background_volume`（-40 到 -6 dB，預設 -20）。帶入時系統 SHALL 產生與人聲等長的背景、頭尾淡入淡出，並在人聲出現時壓低背景後混音；未帶入時輸出 SHALL 與原本相同。未知的背景名稱 SHALL 回 400 並列出可選項。
Read-aloud SHALL optionally mix a named ambience under the voice, ducked and faded, without changing the default output.

#### Scenario: 雨聲背景 / Rain under the voice

- **WHEN** 朗讀請求帶 `jiezi_background: "rain"`
  A speech request sets `jiezi_background` to `rain`
- **THEN** 回傳的音檔長度與人聲相同，背景在人聲出現時被壓低
  The returned audio has the voice's length with the rain ducked under speech

#### Scenario: 未知的背景 / Unknown ambience

- **WHEN** `jiezi_background` 不是內建名稱
  The name is not a preset
- **THEN** 回應 400 並列出可選的背景名稱
  It answers 400 listing the presets
