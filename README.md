---
title: Bloom Ware
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
---

# 🌱 Bloom Ware on HuggingFace Spaces

Bloom Ware 由 **銘傳大學 人工智慧應用學系「槓上開發」** 團隊打造並維護，現在搬到 HuggingFace Spaces 給大家試玩。這份 README 也是 Space 的設定檔，記得留著。

## ✨ 你會看到什麼
- ⚙️ 後端採 FastAPI，入口統一在 `app.py`。
- 🧠 內建 Firebase、語音登入、MCP Agent 橋接等服務，冷啟即用。
- 💤 免費計算資源有限，背景排程預設關閉，必要時自己開。

## 🚀 快速部署步驟
1. 建好 Space 後會自動 `pip install -r requirements.txt`，不用動。
2. 別覆蓋 `PORT`，HuggingFace 會給 `PORT=7860`，服務會自動抓。
3. 到 **Settings → Secrets** 補齊所有敏感環境變數，另外加上  
   - `ENABLE_BACKGROUND_JOBS=false`（免費機器就別硬跑排程）  
   - 任何金鑰、密碼、Firebase JSON 都放 Secrets，不要 commit。

## 🧪 本地或 Space 驗證
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ENABLE_BACKGROUND_JOBS=false PORT=7860 python app.py
```
走 `http://127.0.0.1:7860` 看畫面是否正常，再 decide 要不要推到 Space。

## 📦 推上 HuggingFace
```bash
（已移除 HuggingFace/SpeechBrain 相依，無需設定 token）
cd Bloom_Ware
# 將最新程式碼覆蓋進來
git add .
git commit -m "同步 Bloom Ware 最新變更"
git push
# 出現 password 提示時，貼上剛剛的 access token
```

## 🧠 設定小抄
- `ENABLE_BACKGROUND_JOBS`：在 HuggingFace 建議設 `false`，避免快取維護、批次任務、清理排程耗掉寶貴 CPU；若搬回 Render 或其他長駐環境，再調回 `true`。
- 其他 Render 時期的環境變數照舊，沒有特別兼容性的 hack。

## 🤝 團隊資訊
我們是銘傳大學人工智慧應用學系的 **槓上開發**，專注把 AI 工具塞進實際應用。如果覺得好用，請幫 Space 點顆 ⭐️，或開 Issue/PR 跟我們互嗆（友善互動）。歡迎合作 🙌 
