# Hugging Face Space Deployment

## Target

- Space: `XiaoBai1221/Bloom_Ware`
- URL: `https://hf.co/spaces/XiaoBai1221/Bloom_Ware`
- SDK: `docker`
- App port: `7860`

## Runtime Shape

- API server: `FastAPI`
- Entry point: `app.py`
- Main frontend: `static/frontend`
- Login frontend build output: `bloom-ware-login/out`

`app.py` 會掛載：

- `/static` -> `static/frontend`
- `/login` -> `bloom-ware-login/out`

因此 Docker image 在 build 階段必須先完成 `bloom-ware-login` 的 `npm run build`。

## Deployment Files

- `README.md`
  - Hugging Face Space metadata
  - deployment quickstart
- `Dockerfile`
  - Python runtime
  - Node.js build for `bloom-ware-login`
  - `uvicorn` startup command
- `.dockerignore`
  - exclude local secrets, tests, git metadata, temporary files
- `requirements.txt`
  - runtime dependencies only
- `requirements-dev.txt`
  - local test dependencies

## Secret Handling

不要把以下內容提交到 repo，也不要讓它們進入 Docker build context：

- `.env`
- `.env.*`
- `config.json`
- Firebase service account JSON
- Google speech service account JSON

Hugging Face Space 內請改用 `Settings -> Secrets` 設定。

## Push Flow

既有 remote 已對到 Hugging Face：

```bash
git remote -v
```

應看到：

```bash
hf https://huggingface.co/spaces/XiaoBai1221/Bloom_Ware
```

推送流程：

```bash
git add README.md Dockerfile .dockerignore requirements.txt requirements-dev.txt docs/huggingface-space-deployment.md
git commit -m "Prepare Bloom Ware for Hugging Face Space deployment"
git push hf main
```

若出現驗證提示：

- username: `XiaoBai1221`
- password: Hugging Face User Access Token

## Verification Checklist

- `README.md` YAML 包含 `sdk: docker`
- `README.md` YAML 包含 `app_port: 7860`
- `.dockerignore` 已排除 `.env` 與憑證 JSON
- `bloom-ware-login/package-lock.json` 存在，`Dockerfile` 可用 `npm ci`
- `app.py` 仍以 `${PORT:-7860}` 啟動
- Space Secrets 已補齊

## Known Risks

- BM runtime 依賴 `torch`、`torchaudio`、`speechbrain`、`transformers`，Docker build 仍偏重，首次 build 會慢。
- 若 `bloom-ware-login` 的 Next.js 輸出策略改變，需同步確認 `app.py` 掛載的 `bloom-ware-login/out` 是否仍存在。
- 若 Space secrets 缺漏，build 會過，但 runtime 可能在啟動後才報錯。
