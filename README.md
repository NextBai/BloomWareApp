---
title: Bloom Ware
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
---

# Bloom Ware - 個人化助理「小花」🌺

**Bloom Ware** 的專屬個人化助理 **「小花」**，是由 **銘傳大學人工智慧應用學系** 的 **「槓上開發」** 團隊所精心研發的陪伴型人工智慧系統。

🏆 **榮譽肯定：本專案於民國 115 年榮獲系上專題特優第一名！**

## 關於小花 (About Xiao Hua)

小花不只是一個普通的語音助理，而是一個具備「情感共鳴」與「上下文感知」能力的沉浸式對話夥伴。透過深度學習技術分析使用者的語氣與情緒，小花能夠主動切換至「關懷模式」，在使用者經歷低潮或負面情緒時，給予溫暖的心理支持與陪伴。

## 🌟 核心特色 (Core Features)

- **即時語音對話 (Real-time Voice Interaction)**：透過 WebSocket 實現極低延遲的 STT 與 TTS 雙向語音互動。
- **語音聲紋登入 (Voice Authentication)**：結合 `SpeechBrain` 實現聽聲辨人，提供無密碼的流暢登入體驗。
- **情感分析與關懷 (Emotion Detection & Care Mode)**：即時捕捉語音與文字中的情緒（如悲傷、憤怒、恐懼），自動提供同理心關懷。
- **MCP 擴充助手 (Model Context Protocol)**：內建天氣、交通 (TDX)、地圖編碼與健康數據等生活助手功能，隨時為您提供所需資訊。
- **長期記憶 (Long-Term Memory)**：整合 Firestore 與背景排程進行記憶摘要，讓小花記得與您的每一次重要對話。

> 💡 **進階技術文件**：關於詳細的系統架構、API 說明與功能解析，請參閱 `docs/` 目錄下的完整文件。
> - [系統架構說明 (Architecture)](/Users/baidongqu/Desktop/BM/docs/architecture.md)
> - [核心功能詳解 (Features)](/Users/baidongqu/Desktop/BM/docs/features.md)
> - [Hugging Face 部署指南](/Users/baidongqu/Desktop/BM/docs/huggingface-space-deployment.md)

---

## 🚀 部署與運行資訊 (Deployment & Run Information)

Bloom Ware 目前以 **Hugging Face Docker Space** 方式部署到 `XiaoBai1221/Bloom_Ware`。

### Deployment Target

- Space: [`XiaoBai1221/Bloom_Ware`](https://hf.co/spaces/XiaoBai1221/Bloom_Ware)
- SDK: `docker`
- Exposed port: `7860`
- Git remote: `hf`

### Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
ENABLE_BACKGROUND_JOBS=false PORT=7860 python app.py
```

本地驗證網址：`http://127.0.0.1:7860`

### Hugging Face Space Deploy

1. 在 Hugging Face Space `Settings -> Secrets` 補齊敏感環境變數。
2. 不要提交 `.env`、Firebase 憑證 JSON、或任何本地設定檔。
3. 確認 `README.md` 頂部 YAML 維持 `sdk: docker` 與 `app_port: 7860`。
4. 直接推送到既有 Space remote：

```bash
git add README.md Dockerfile .dockerignore requirements.txt requirements-dev.txt docs/
git commit -m "Prepare Bloom Ware for Hugging Face Space deployment"
git push hf main
```

若 Git 要求帳密，帳號用 Hugging Face 帳號，密碼改貼 **User Access Token**。

### Required Secrets

至少補齊這些類型：

- `OPENAI_API_KEY`
- `FIREBASE_PROJECT_ID`
- `FIREBASE_CREDENTIALS_JSON` 或 `FIREBASE_SERVICE_ACCOUNT_JSON_BASE64`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_API_KEY`
- `GOOGLE_SPEECH_PROJECT_ID`
- `GOOGLE_SPEECH_CREDENTIALS_JSON` 或 `GOOGLE_SPEECH_SERVICE_ACCOUNT_JSON_BASE64`
- `TDX_CLIENT_ID`
- `TDX_CLIENT_SECRET`
- `OPENROUTESERVICE_API_KEY`

建議同時設定：

- `ENABLE_BACKGROUND_JOBS=false`
- `PORT=7860`

### Notes

- Space build context 已排除 `.env`、憑證 JSON、`tests/`、`.git/`，避免本地敏感檔被包進 Docker image。
- `requirements.txt` 只保留 runtime 依賴；本地測試改裝 `requirements-dev.txt`。
- 更完整的部署說明在 [docs/huggingface-space-deployment.md](/Users/baidongqu/Desktop/BM/docs/huggingface-space-deployment.md)。
