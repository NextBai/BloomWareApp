# Repository Guidelines + System Architecture

結論先講：本專案是 FastAPI 單體後端，走 WebSocket 主動互動、REST 做周邊能力，資料層以 Firestore 為核心，功能透過 MCP Tools 解耦；本檔已補齊實際架構、流程、環境與風險，照著做就不會踩雷。

**目錄速覽**
- `app.py`：ASGI 入口（FastAPI）。載入設定、掛載靜態檔、CORS/CSP、中介層、背景任務、WebSocket `/ws`、OAuth 與 REST API。
- `core/`：設定（`config.py`）、認證（`auth/` JWT + Google OAuth PKCE）、資料庫（`database/` Firestore + 快取 + 最佳化）、記憶系統、情緒關懷、聊天處理管線。
- `features/mcp/`：MCP 伺服器與工具（天氣、新聞、匯率、HealthKit 查詢等），`agent_bridge.py` 負責意圖偵測與工具串接。
- `services/`：AI 產生（OpenAI SDK）、TTS/STT、語音登入、批次排程等服務層。
- `models/`：語音情緒與說話者辨識相關模型與腳本。
- `static/`：前端靜態頁（登入、對話 UI 等）。
- `tests/`：Pytest 測試，鏡射模組路徑（目前以 `services/voice_login` 為主）。
- `render.yaml`、`Dockerfile`、`runtime.txt`、`.env.production.example`：部署與環境樣板。
- `bloom-ware-login/`：獨立 Next.js（登入）樣板，非後端運行必要。

—

**執行與開發（本機）**
- 建環境：`python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- 直跑：`python app.py`（預設 0.0.0.0:8080）
- ASGI 模式：`uvicorn app:app --reload`（開發用）
- 前端入口：`/static/login.html` → 走 Google OAuth 登入 → 以 JWT 綁 WebSocket `/ws?token=...`。
- 測試：`pytest -q` 或 `pytest -q -k voice_login`。

提示：Docker/HF Spaces 預設 `PORT=7860`；Render 預設 `PORT=10000`。程式以環境變數為準。

—

**系統架構（重點元件）**
- Web 層：FastAPI + 中介層（CORS、CSP）。靜態檔以 `static/frontend` 掛載到 `/static`。
- WebSocket：`/ws` 單點，JWT 驗證（Query `token`），集中處理聊天、typing 與工具回傳；`ConnectionManager` 管理會話。
- 意圖與工具：`features/mcp/agent_bridge.py` 以 OpenAI Structured Outputs 做意圖偵測，命中則調 `features/mcp/tools/*`（天氣/新聞/匯率/HealthKit 等）。
- 聊天管線：`core/pipeline.ChatPipeline` 先意圖→工具→AI 產生；支援「情緒關懷模式」（極端情緒時停用工具、改走關懷 Prompt）。
- AI 服務：`services/ai_service.py` 封裝 OpenAI SDK；模型由環境 `OPENAI_MODEL` 控（預設 `gpt-5-nano`）。
- 資料層：Firestore（`core/database/base.py`）＋最佳化存取與 LRU 快取（`optimized.py`/`cache.py`）；集合：`users`、`chats`、`messages`、`health_data`、`device_bindings`。
- 背景任務：啟動時依 `ENABLE_BACKGROUND_JOBS` 啟動快取維護、清理、批次排程（每日摘要/週報）。

—

**請求流程（典型路徑）**
- 登入：前端打 `/auth/google/url` 取得授權連結 → Google 回調 `/auth/google/callback` → 交換 Token → 產出 JWT。
- 對話：前端以 `/ws?token=JWT` 連上；訊息先經「語音綁定 FSM」攔截（若用語音綁定流程）→ 進入 `ChatPipeline` → 視意圖走 MCP 工具或一般聊天 → 落庫 `chats/messages`。
- 檔案分析：`/api/upload-file` 或 `/api/analyze-file-base64`，文字/PDF/圖片分流到對應分析邏輯，底層仍透過 OpenAI。
- 健康資料：建議透過 MCP `healthkit_tool` 查 Firestore（iOS 端直寫 `health_data`）。
- 位置快照：前端成功取得瀏覽器定位時會透過 `env_snapshot` 送到 WebSocket；後端會自動寫入 Firestore 並呼叫 MCP `reverse_geocode` 反查地點，AI Prompt 只會顯示地點名稱（有 label）或地址（無 label），不再硬編碼地標。

—

**環境與設定（`core/config.Settings`）**
- 必填：`FIREBASE_PROJECT_ID`、`FIREBASE_CREDENTIALS_JSON`（或 `FIREBASE_SERVICE_ACCOUNT_PATH`）、`OPENAI_API_KEY`、`GOOGLE_CLIENT_ID/SECRET`、`JWT_SECRET_KEY`。
- 其他：`OPENAI_MODEL`（預設 `gpt-5-nano`）、`HOST`、`PORT`、`ENABLE_BACKGROUND_JOBS`、第三方金鑰（天氣/新聞/匯率）。
- 生產：Render 用 `PORT=10000`，HF Spaces/Docker 用 `PORT=7860`。

—

**部署模式**
- Render（`render.yaml`）：平台注入環境變數，直接 `python3 app.py` 啟動。
- HF Spaces（`Dockerfile`）：以 `uvicorn` 啟動，`PORT` 由平台給；請關閉排程（`ENABLE_BACKGROUND_JOBS=false`）。

—

**測試策略（TDD）**
- 測試放 `tests/`，鏡射原始碼路徑，命名 `test_*.py`。
- 先紅後綠再重構；關鍵路徑優先（`core/`、`services/`）。
- 範例：`tests/services/test_voice_login_cnn.py` 透過 stub/injection 減少重量相依。

—

**MCP 工具擴充規範（快速上手）**
- 位置：`features/mcp/tools/`；繼承 `MCPTool`，實作 `get_input_schema`、`get_output_schema`、`execute`。
- 自動註冊：`features/mcp/auto_registry.py` 會掃描並註冊；若需要外部進程，交由 `server.start_external_servers()`。
- 輸出格式：以 `create_success_response(content=..., data=...)` 回傳；錯誤用 `create_error_response(code=..., error=...)`。
- 工具 metadata：`CATEGORY/TAGS/USAGE_TIPS` 會回到 `/api/mcp/tools` 供前端工具卡片用。

—

**安全與維運建議（務必看完）**
- CORS：目前設定為 `allow_origins=["*"]` 且 `allow_credentials=True`，生產環境建議收斂來源網域，避免 Cookie/Authorization 外洩風險。
- JWT：請務必提供穩定的 `JWT_SECRET_KEY`；否則服務重啟會因隨機 Secret 導致既有 Token 全失效。
- CSP：為了語音前端放寬到 `'unsafe-inline'/'unsafe-eval'`，生產環境請只在 `/static` 下放寬，嚴禁波及 API 路徑。
- 上傳限制：檔案上限 10MB，白名單含 PDF/影像/程式碼等，後端已驗型別但仍需注意前端檔案來源。
- Firestore 配額：已實作 LRU 快取、請求合併與批次寫入；高流量時請觀察 `/api/performance/stats`。

—

**已知問題（歡迎開 PR 修）**
- `requirements.txt` 尾端疑似誤合併文字，出現 `transformersservices:`；若安裝失敗，請將 `transformers` 與 `services:` 拆正（`render.yaml` 應在獨立檔）。
- `app.py` 的 CORS 設定呼叫了兩次，可合併為一次以避免重複中介層。
- `GET /api/health/query` 仍殘留 Mongo-style 的 `find()`/`async for` 寫法，與 Firestore 用法不符；建議改用 MCP `healthkit_tool` 或重寫為 Firestore 查詢。

—

**Coding Style & Conventions**
- Python 3.10+；`ruff/black` 預設（88 cols, 4-space, UTF‑8）。
- 模組 `snake_case.py`；類別 `PascalCase`；函式/變數 `snake_case`。
- 分層：Controller(API) → Service → Core/Utils；資料層封在 `core/database/*`。
- 環境變數透過 `os.environ` 讀取；範例見 `.env.production.example`。

—

**Agent-Specific（給在此倉工作之助理）**
- 語言與語氣：全程繁中（台灣），「先結論、後細節」，可微嗆不冒犯。
- TDD：先寫測試（紅燈）→ 最小實作（綠燈）→ 重構，每個功能至少跑完一輪。
- OpenAI 使用：以 Python SDK；模型由 `OPENAI_MODEL` 控制（預設 `gpt-5-nano`）；若改版，請只改環境變數，不要在程式寫死。
- 測試放置：所有測試集中於 `tests/`，`test_*.py`；結構鏡射模組路徑。
- 前端語音介面：`static/frontend/index.html` 的 `voice-center-container`、`voice-agent-output`、`voice-transcript` 已改為彈性寬高；打字態訊息只做 opacity/visibility 切換，避免擠壓字幕區。調整樣式時請維持 `clamp` 設定與 wrapper class，確保桌機/平板視窗自適應。
