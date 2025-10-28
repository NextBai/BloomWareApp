# 🚀 Bloom Ware Render 部署指南

## 📋 前置準備

### 1. 生成新的 JWT Secret（生產環境專用）
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```
複製輸出的字串，稍後會用到。

### 2. 將 Firebase JSON 轉為單行字串
```bash
cat your-firebase-credentials.json | python3 -m json.tool --compact | pbcopy
```
（macOS 會自動複製到剪貼簿）

---

## 🔧 Render 部署步驟

### 步驟 1：推送程式碼到 GitHub
```bash
git add .
git commit -m "準備 Render 部署：統一配置管理 + Firebase 環境變數化"
git push origin main
```

### 步驟 2：在 Render 建立 Web Service
1. 登入 [Render](https://render.com/)
2. 點擊 **New** → **Web Service**
3. 連接 GitHub 倉庫：選擇 `bloom-ware`
4. 設定：
   - **Name**: `bloom-ware`（或自訂名稱）
   - **Region**: `Singapore` 或 `Oregon`
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`

### 步驟 3：設定環境變數
在 Render Dashboard → Environment 頁面，新增以下環境變數：

#### 必要環境變數（16 項）

| 變數名 | 值 | 說明 |
|--------|-----|------|
| `ENVIRONMENT` | `production` | 環境識別 |
| `FIREBASE_PROJECT_ID` | `your-firebase-project-id` | Firebase 專案 ID |
| `FIREBASE_CREDENTIALS_JSON` | `{"type":"service_account",...}` | **完整 JSON 字串（單行）** |
| `OPENAI_API_KEY` | `sk-proj-...` | OpenAI API Key |
| `OPENAI_MODEL` | `gpt-5-nano` | 模型名稱 |
| `OPENAI_TIMEOUT` | `30` | 超時秒數 |
| `GOOGLE_CLIENT_ID` | `your-google-client-id.apps.googleusercontent.com` | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | `GOCSPX-...` | Google OAuth Secret |
| `GOOGLE_REDIRECT_URI` | `https://your-app.onrender.com/auth/google/callback` | **OAuth 回調 URI** |
| `WEATHER_API_KEY` | `your-weather-api-key` | OpenWeatherMap Key |
| `NEWSDATA_API_KEY` | `pub_xxxxx` | NewsData.io Key |
| `EXCHANGE_API_KEY` | `your-exchange-api-key` | ExchangeRate Key |
| `JWT_SECRET_KEY` | `YOUR_NEW_SECRET` | **新生成的 Secret** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token 有效期 |
| `HOST` | `0.0.0.0` | 監聽主機 |
| `PORT` | `10000` | Render 固定端口 |

### 步驟 4：部署
點擊 **Create Web Service**，Render 會自動：
1. 執行 `pip install -r requirements.txt`
2. 啟動 `python app.py`
3. 提供 HTTPS URL（例如：`https://bloom-ware-xxxx.onrender.com`）

---

## 🔗 Google OAuth 回調 URI 更新

### 1. 前往 Google Cloud Console
https://console.cloud.google.com/apis/credentials

### 2. 選擇你的 OAuth 2.0 客戶端

### 3. 新增「已授權的重新導向 URI」
```
https://bloom-ware-xxxx.onrender.com/auth/google/callback
```
（替換為你的實際 Render 網址）

### 4. 儲存變更

### 5. 更新 Render 環境變數
回到 Render Dashboard → Environment，更新：
```
GOOGLE_REDIRECT_URI=https://bloom-ware-xxxx.onrender.com/auth/google/callback
```

---

## ✅ 驗證部署

### 1. 檢查 Logs
在 Render Dashboard → Logs 查看：
```
✅ Firebase Firestore連接成功！專案ID：your-project-id
✅ OpenAI 客戶端初始化完成
🚀 Bloom Ware 後端服務器啟動中...
```

### 2. 測試連接
訪問：`https://your-app.onrender.com`
應該看到前端登入頁面

### 3. 測試 Google 登入
1. 點擊「使用 Google 登入」
2. 授權後應該成功跳轉並登入

---

## 🐛 常見問題

### 問題 1：Firebase 憑證錯誤
**錯誤訊息**：`Firebase 憑證載入失敗`

**解決方式**：
- 確認 `FIREBASE_CREDENTIALS_JSON` 是**單行字串**（無換行符）
- 檢查 JSON 格式是否正確（使用 `python3 -m json.tool` 驗證）

### 問題 2：Google OAuth 回調失敗
**錯誤訊息**：`redirect_uri_mismatch`

**解決方式**：
- 確認 Google Cloud Console 已新增 Render 回調 URI
- 確認 `GOOGLE_REDIRECT_URI` 環境變數正確

### 問題 3：應用休眠（免費方案）
**現象**：閒置 15 分鐘後，首次訪問需等待 30 秒

**解決方式**：
- 升級到付費方案（$7/月）
- 或使用 UptimeRobot 定期 ping（每 14 分鐘）

---

## 📝 部署後清單

- [ ] 測試 Google 登入流程
- [ ] 測試 WebSocket 連接
- [ ] 測試語音功能（錄音 + TTS）
- [ ] 測試 MCP 工具（天氣、新聞、匯率）
- [ ] 檢查 Firebase Firestore 資料寫入
- [ ] 監控 Render Logs 是否有錯誤

---

## 🔄 更新部署

每次程式碼更新後：
```bash
git add .
git commit -m "更新功能"
git push origin main
```

Render 會自動檢測並重新部署（約 2-3 分鐘）。

---

## 📞 支援

遇到問題？檢查：
1. Render Dashboard → Logs
2. Render Dashboard → Events
3. GitHub Actions（如有設定 CI/CD）

---

**🎉 恭喜！Bloom Ware 已成功部署到 Render！**
