---
title: Bloom Ware
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
---

# Bloom Ware

Bloom Ware 目前以 **Hugging Face Docker Space** 方式部署到 `XiaoBai1221/Bloom_Ware`。
後端是 `FastAPI`，入口在 `app.py`；登入頁由 `bloom-ware-login` 建成靜態檔後掛到 `/login`；主前端則由 `static/frontend` 提供。

## Deployment Target

- Space: [`XiaoBai1221/Bloom_Ware`](https://hf.co/spaces/XiaoBai1221/Bloom_Ware)
- SDK: `docker`
- Exposed port: `7860`
- Git remote: `hf`

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
ENABLE_BACKGROUND_JOBS=false PORT=7860 python app.py
```

本地驗證網址：`http://127.0.0.1:7860`

## Hugging Face Space Deploy

1. 在 Hugging Face Space `Settings -> Secrets` 補齊敏感環境變數。
2. 不要提交 `.env`、Firebase 憑證 JSON、或任何本地設定檔。
3. 確認 `README.md` 頂部 YAML 維持 `sdk: docker` 與 `app_port: 7860`。
4. 直接推送到既有 Space remote：

```bash
git add README.md Dockerfile .dockerignore requirements.txt requirements-dev.txt docs/huggingface-space-deployment.md
git commit -m "Prepare Bloom Ware for Hugging Face Space deployment"
git push hf main
```

若 Git 要求帳密，帳號用 Hugging Face 帳號，密碼改貼 **User Access Token**。

## Required Secrets

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

## Notes

- Space build context 已排除 `.env`、憑證 JSON、`tests/`、`.git/`，避免本地敏感檔被包進 Docker image。
- `requirements.txt` 只保留 runtime 依賴；本地測試改裝 `requirements-dev.txt`。
- 更完整的部署說明在 [docs/huggingface-space-deployment.md](/Users/baidongqu/Desktop/BM/docs/huggingface-space-deployment.md)。
