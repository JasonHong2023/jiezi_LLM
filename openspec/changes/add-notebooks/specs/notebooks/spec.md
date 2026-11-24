## ADDED Requirements

### Requirement: Persistent Notebooks Of Sources / 保存來源的筆記本
系統 SHALL 讓使用者建立多本筆記本，每本可加入檔案、網址、貼上的文字與音檔／影片（轉逐字稿）作為來源，並保存在本機 `var/notebooks/`。每份來源 SHALL 記錄標題、種類、原始檔名或網址、sha256、加入時間與信任等級；內容相同的來源 SHALL NOT 重複加入；段落 SHALL 保留在原文中的字元位置。每份來源 SHALL 經提示注入掃描，可疑的來源 SHALL 標記並在引用時警示。
Users SHALL keep notebooks of sources locally, deduplicated, with chunk offsets and trust levels.

#### Scenario: 重複加入 / Duplicate source

- **WHEN** 同一份 PDF 第二次加入同一本筆記本
  The same PDF is added twice
- **THEN** 不新增來源，回報已存在
  No new source is created; it reports the existing one

#### Scenario: 音檔來源 / Audio source

- **WHEN** 加入一段 10 分鐘的會議錄音
  A ten-minute recording is added
- **THEN** 以語音辨識轉成帶時間碼的逐字稿作為來源全文
  It is transcribed with timestamps and stored as the source text

### Requirement: Answers With Verified Citations / 附經檢查引用的回答
在筆記本內的提問 SHALL 只用該筆記本的來源段落回答，每句事實 SHALL 標註引用編號，編號 SHALL 對應提供給模型的段落。引用檢查器 SHALL 移除不存在或與該句內容不符的引用並標示「（未找到出處）」。來源中找不到相關段落時 SHALL 明說找不到，除非請求允許補充一般知識且明確標示非出自來源的部分。回答 SHALL 附上引用清單（來源、段落、字元位置、原文摘句），讓介面能跳到原文。
Notebook answers SHALL use only that notebook's passages with checked sentence-level citations, and SHALL say so when nothing relevant exists.

#### Scenario: 編造的引用 / Fabricated citation

- **WHEN** 模型在一句與段落 [3] 無關的話後面標了 [3]
  The model cites [3] after a sentence unrelated to passage 3
- **THEN** 移除該引用並標示「（未找到出處）」
  The citation is removed and the sentence is marked as unsourced

#### Scenario: 來源沒有答案 / No answer in the sources

- **WHEN** 問題與所有來源都無關
  The question is unrelated to every source
- **THEN** 回答這本筆記本的來源裡找不到，不靠一般知識作答
  It says the sources do not cover it instead of answering from general knowledge

### Requirement: Notebooks And Long-Term Memory / 筆記本與長期記憶結合
筆記本問答 SHALL 附上使用者要芥子記住的事與相關的使用者更正。每本筆記本 SHALL 在記憶 wiki 有一頁摘要（來源清單與各來源摘要），來源變動時 SHALL 更新。`JIEZI_NOTEBOOK_RECALL`（預設開）時，一般對話問到筆記本涵蓋的主題 SHALL 從該筆記本取段落回答並引用。筆記本內容與由它產生的回答 SHALL 預設標記為不可用於訓練。
Notebooks SHALL read the user's notes and corrections, publish a summary page to the memory wiki and be recallable from normal chat (on by default); private content is not trainable by default.

#### Scenario: 一般對話想起筆記本 / Normal chat recalls a notebook

- **WHEN** 使用者在一般對話問「上次那份租約的押金是幾個月？」，而筆記本《租屋》有這份租約
  A normal chat asks about a lease kept in a notebook
- **THEN** 芥子從《租屋》取段落回答，並引用該租約
  Jiezi answers from that notebook's passages with citations

### Requirement: Verified Automatic Saving To Memory / 查證後自動存進記憶
每則筆記本回答 SHALL 自動查證，全部通過才寫進記憶主題頁（種類 notebook、記錄筆記本與來源段落、不可訓練）。查證 SHALL 包含：每句事實都有通過檢查的出處；被引用的來源之間沒有矛盾；與記憶中的使用者更正及先前存過的答案沒有衝突；被引用的來源未被提示注入掃描標記或標為 tainted；回答沒有不確定語句、問題沒有含糊之處。沒通過時 SHALL NOT 寫入，SHALL 向使用者列出每一項發現（哪一句、什麼問題），並提供「仍要存」與「我來更正」；使用者選「仍要存」時 SHALL 寫入並註明查證結果。
Every notebook answer SHALL be checked and saved to memory only when every check passes; otherwise the findings SHALL be shown and saving SHALL wait for the user.

#### Scenario: 來源互相矛盾 / Conflicting sources

- **WHEN** 回答引用的兩份來源，一份寫押金 2 個月、一份寫 3 個月
  Two cited sources disagree on the deposit
- **THEN** 不存進記憶，列出「來源 A 說 2 個月、來源 B 說 3 個月」，等使用者決定
  Nothing is saved; the conflict is listed and the user decides

#### Scenario: 全部通過 / All checks pass

- **WHEN** 每句都有正確出處、來源一致、沒有衝突也沒有不確定之處
  Every check passes
- **THEN** 自動寫進記憶，回答下方顯示「已存進記憶」
  It is saved automatically and the answer shows it was saved

#### Scenario: 與更正衝突 / Conflict with a correction

- **WHEN** 回答與使用者先前的更正不同
  The answer contradicts an earlier user correction
- **THEN** 不存，列出「與你某日的更正不同」並附上該更正
  Nothing is saved; the conflicting correction is shown
