# 系統架構說明 (System Architecture)

Bloom Ware 「小花」專案採用現代化的前後端分離架構，結合多項領先的 AI 技術與穩定可擴展的後端框架。

## 1. 後端架構 (Backend - FastAPI)

後端採用 Python 的 **FastAPI** 框架，提供非同步、高效能的 API 服務與 WebSocket 長連接管理。

- **`app.py`**: 應用的進入點。負責配置 Lifespan（啟動/關閉事件）、Middleware（如 CORS, CSP）、定義 WebSocket 的連線（`/ws`），並掛載靜態前端資源。
- **`core/` (核心邏輯)**:
  - **資料庫 (`database/`)**: 與 Firebase Firestore 進行連線，處理使用者資料、對話紀錄與記憶的 CRUD 操作。
  - **驗證 (`auth.py`)**: 處理 JWT Token 生成與解析，並整合 Google OAuth 登入機制。
  - **Pipeline (`pipeline.py`)**: 負責串接使用者的輸入到大語言模型（LLM）的資料流。
  - **記憶體系統 (`memory_system.py`)**: 管理對話上下文，提供 AI 摘要。
- **`features/` 與 `services/` (業務與 AI 服務)**:
  - 封裝了與 OpenAI 溝通的 `ai_service.py`。
  - `voice_binding.py`: 負責聲紋註冊狀態機管理。
  - MCP (Model Context Protocol) 工具集：整合天氣、交通 (TDX)、位置查詢等外部 API。
- **`websocket/`**:
  - `manager.py`: 管理所有連線的使用者會話，處理訊息派發、連線逾時清理等。

## 2. 前端架構 (Frontend)

本系統將前端拆分為「登入驗證層」與「沉浸式互動層」。

- **登入介面 (`bloom-ware-login/out`)**:
  - 基於 **Next.js** 與 React 構建，編譯為靜態資源後由 FastAPI 掛載於 `/login` 路徑。
  - 提供 Google 登入、一般信箱登入，以及跳轉至語音註冊的入口。
- **主互動介面 (`static/frontend/`)**:
  - 專注於 **沉浸式語音體驗** 的純靜態應用（HTML/CSS/JS）。
  - 以「小花」的視覺形象（如動態花朵動畫）作為介面核心。
  - 透過 WebRTC/MediaRecorder 擷取音訊，透過 WebSocket 傳送給後端，並將後端回傳的音訊進行播放，且畫面會隨情緒狀態與音量產生動態回饋。

## 3. 基礎設施與部署 (Infrastructure)

- **Docker 化**: 提供完整的 `Dockerfile`，確保在各種環境下執行的一致性。
- **Hugging Face Space**: 系統原生設計為可直接部署於 Hugging Face Space 上，支援無伺服器架構的容器化執行。
- **排程與背景任務**:
  - 啟動時即開啟 `asyncio` 背景任務，定期清理過期的 WebSocket 會話、壓縮並總結歷史對話，確保長期執行的效能與穩定度。
