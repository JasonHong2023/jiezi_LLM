## ADDED Requirements

### Requirement: Typed URLs
The gateway SHALL fetch http and https URLs written in the last user message (at most 3, GET only, HTML or plain text, at most 5 MB, 15-second timeout, at most 5 redirects), SHALL refuse loopback, private and link-local addresses including after redirects, SHALL attach the extracted text as a document treated as data, SHALL NOT route such a question as needing the web when the page was read, and SHALL store a local summary in memory when the user asks to remember the page.

#### Scenario: 讀網址並記住 / Read and remember a URL
- **WHEN** 使用者說「仔細閱讀這個網址的內容並記憶起來 https://docs.python.org/3/」
  The user asks to read and remember a page
- **THEN** gateway 讀取網頁、本機作答，不請教 Claude；重點存進記憶 wiki，metadata `web_read` 記 ok
  The page is read locally, answered without Claude, and a summary is stored in memory

#### Scenario: 內網位址 / A private address
- **WHEN** 網址是 http://192.168.1.1/ 或轉址到 127.0.0.1
  The URL or a redirect points at a private address
- **THEN** 不讀取，metadata 記原因
  It is not fetched and the reason is recorded
