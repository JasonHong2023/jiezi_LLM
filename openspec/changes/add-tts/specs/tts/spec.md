## ADDED Requirements

### Requirement: Local Speech Synthesis Endpoint / 本機語音合成端點
gateway SHALL 提供 OpenAI 相容的 `POST /v1/audio/speech` 與 `GET /v1/audio/voices`，以 BlueMagpie-TTS 在本機合成語音。端點 SHALL 只在 `JIEZI_TTS=on` 時啟用（預設關），SHALL 要求 gateway 金鑰。`input` SHALL 不超過 20,000 字，超過一段的長度 SHALL 依標點分段合成後接起來；`response_format` SHALL 為 wav、mp3、flac 或 opus；`voice` SHALL 只能是內附語者或已登錄的聲音，未指定時 SHALL 用 `female_voice`。請求 SHALL NOT 能夾帶參考音檔、音檔路徑或語者向量。
The gateway SHALL offer OpenAI-compatible speech endpoints, off by default and key-protected; long input is split at punctuation; voices are limited to bundled or enrolled ones (default female_voice); requests cannot carry reference audio.

#### Scenario: 未啟用 / Disabled

- **WHEN** `JIEZI_TTS` 不是 on
  TTS is not enabled
- **THEN** 回 404，不啟動任何行程
  404 and no process is started

#### Scenario: 請求夾帶參考音檔 / Reference audio in a request

- **WHEN** 請求帶參考音檔、音檔路徑、語者向量或不在名單的 voice
  The request carries reference audio, a path, a speaker vector or an unknown voice
- **THEN** 回 400，說明聲音只能在本機登錄
  400 explaining that voices can only be enrolled locally

#### Scenario: 長文 / Long text

- **WHEN** `input` 是 5,000 字的文章
  The input is a 5,000-character article
- **THEN** 依標點分段合成、段間加停頓，回傳一個完整音檔
  It is synthesized in punctuation-bounded chunks and returned as one file

### Requirement: Consented Local Voice Enrollment / 經同意且只能在本機登錄聲音
新聲音 SHALL 只能由使用者在本機以 `scripts/jiezi tts voice add <名稱> <參考音檔> --consent "<說明>"` 登錄；`--consent` SHALL 必填；參考音檔 SHALL 為 3–60 秒，轉成 16 kHz 單聲道存於 `var/tts/voices/`；登錄表 SHALL 記錄名稱、同意聲明、登錄時間與音檔 sha256。API、代理工具與網頁 SHALL NOT 提供登錄或上傳參考音檔的方法。用登錄聲音合成時，合成紀錄 SHALL 標記 `cloned: true`。`voice remove` SHALL 刪除參考音檔與登錄。
Voices SHALL be enrolled only through the local CLI with a mandatory consent statement; no remote path can enroll; cloned output is marked.

#### Scenario: 沒寫同意聲明 / No consent statement

- **WHEN** `voice add` 沒有 `--consent` 或內容空白
  voice add without a consent statement
- **THEN** 拒絕登錄，不保存音檔
  Enrollment is refused and nothing is saved

#### Scenario: 代理想登錄聲音 / An agent tries to enroll a voice

- **WHEN** 模型或代理經 API 或工具嘗試登錄聲音或上傳參考音檔
  A model or agent tries to enroll a voice remotely
- **THEN** 沒有對應的方法；請求回 400 或 404
  No such method exists; 400 or 404

### Requirement: Jiezi Reads Its Answers Aloud / 芥子朗讀回答
桌面網頁 SHALL 在每則回答提供「朗讀」按鈕，`jiezi ask --speak` SHALL 把回答合成並印出音檔路徑；兩者 SHALL 經 `/v1/audio/speech`，朗讀前 SHALL 去掉 Markdown 符號、程式碼區塊與【記憶】等附註。TTS 未啟用時按鈕 SHALL 不顯示。
The desktop page and CLI SHALL read answers aloud through the speech endpoint, stripping markup, code and notes first.

#### Scenario: 回答含程式碼 / Answer with code

- **WHEN** 朗讀一則含程式碼區塊與【記憶】附註的回答
  Reading an answer with a code block and a memory note
- **THEN** 只唸說明文字，程式碼以「（程式碼略）」代替，附註不唸
  Only prose is read; code becomes a short placeholder and notes are skipped

### Requirement: GPU Turn-Taking With The Core / 與核心輪流使用顯示卡
TTS 與核心模型 SHALL NOT 同時占用 GPU。TTS 請求 SHALL 等核心手上的請求完成後卸載核心再啟動 TTS；之後的聊天請求 SHALL 先結束閒置的 TTS 行程再載入核心。TTS 行程閒置 120 秒 SHALL 自動結束。評測保留 GPU（held）期間 TTS 請求 SHALL 被拒絕。
TTS and the core SHALL never share the GPU; each evicts the other only when it is idle, and an evaluation hold blocks TTS.

#### Scenario: 核心正在回答 / Core busy

- **WHEN** 核心正在處理請求時收到 TTS 請求
  A TTS request arrives while the core is answering
- **THEN** TTS 等到核心沒有進行中的請求才卸載核心並合成
  TTS waits until the core is idle, then unloads it and synthesizes

#### Scenario: 朗讀後聊天 / Chat after speech

- **WHEN** TTS 行程閒置時收到聊天請求
  A chat request arrives while the TTS process is idle
- **THEN** 先結束 TTS 行程，再載入核心回答
  The TTS process is stopped first, then the core is loaded

### Requirement: Restricted-Use Weights / 權重限個人研究評估
BlueMagpie-TTS 權重 SHALL 登記於 `docs/licenses.md`（授權不明、僅個人研究評估、不商用、不散布、不作訓練資料），SHALL 以鎖定的 revision 下載並逐檔核對 sha256。權重、參考音檔與合成音檔 SHALL NOT 進版控；音檔 SHALL 只存在本機 `var/tts/out/` 並於 7 天後清除；合成紀錄（`var/tts/log.jsonl`）SHALL 只記字數、語者與耗時，不記音檔與文字內容。TTS 程式 SHALL 在獨立的 Python 環境執行，不改動芥子主環境。
The weights SHALL be registered as personal research use only, pinned and hash-checked; weights and audio SHALL stay local; TTS SHALL run in its own Python environment.

#### Scenario: 權重被改 / Tampered weights

- **WHEN** 下載的權重 sha256 與登記值不符
  A downloaded weight file does not match its recorded sha256
- **THEN** 刪除該檔並停止安裝
  The file is deleted and setup stops
