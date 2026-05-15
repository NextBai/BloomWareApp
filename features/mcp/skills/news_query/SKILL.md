# 新聞與即時資訊查詢 (Tavily AI)

這個 Skill 使用 Tavily API 提供基於 AI 的新聞與即時資訊搜尋。相比傳統新聞 API，Tavily 能夠更好地過濾噪音、提供即時動態並對搜尋結果進行智慧摘要。

## 功能特點
- **極致時效性**：直接串接最新搜尋引擎索引，獲取分秒必爭的時事。
- **AI 摘要**：自動整合多個來源，提供一句話或一段話的精華總結。
- **深度搜尋**：支援 basic 與 advanced 兩種深度，應對簡單查詢或深入研究。

## 參數說明
- `query` (string, 必填): 搜尋關鍵詞。例如：「台積電收盤價」、「2024 奧運獎牌榜」。
- `limit` (integer, 可選): 返回新聞數量，預設 5，上限 10。
- `search_depth` (string, 可選): `basic` (快速) 或 `advanced` (深入)。

## 使用範例
- 「查看今天最重要的科技新聞」 -> `news_query(query="今天科技新聞", limit=5)`
- 「搜尋關於 SpaceX 最近發射任務的詳細報導」 -> `news_query(query="SpaceX 最近發射任務", search_depth="advanced")`
- 「台積電今天收盤多少？」 -> `news_query(query="台積電 股票 收盤價 今天")`

## 注意事項
- Tavily 會自動嘗試理解問題並給出 `answer` (AI 摘要)，這對語音助手快速回報非常有用。
- 本工具已移除舊有的 NewsData.io 邏輯，不再支援 `country` 或 `category` 的硬性篩選，改由 AI 語義搜尋達成。
