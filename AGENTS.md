# Repository Guidelines

## Project Structure & Module Organization
- Root entrypoint: `app.py` (FastAPI/Flask-style server).
- Core logic: `core/` (utilities, config), domain models: `models/`.
- Features and routes: `features/` and `services/` (service layer, APIs).
- Static assets: `static/`.
- Deployment/config: `render.yaml`, `runtime.txt`, `.env.production.example`.
- Tests: place under `features/tests/` or `core/tests/` mirroring module paths.

## Build, Test, and Development Commands
- Create venv: `python3 -m venv .venv && source .venv/bin/activate`.
- Install deps: `pip install -r requirements.txt`.
- Run locally: `python app.py` (or `uvicorn app:app --reload` if ASGI).
- Lint/format (if installed): `ruff check .`, `ruff format .` or `black .`.
- Type check (optional): `mypy .`.

## Coding Style & Naming Conventions
- Python 3.10+. Use `ruff`/`black` defaults: 88 cols, 4-space indent, UTF-8.
- Modules: `snake_case.py`; classes: `PascalCase`; functions/vars: `snake_case`.
- Keep I/O, HTTP, and DB logic separated: controllers → services → core/utils.
- Environment config via `os.environ`; example values in `.env.production.example`.

## Testing Guidelines
- Framework: `pytest` (recommended). Name tests `test_*.py`.
- 測試目錄一律放在根目錄 `tests/`，並以子資料夾鏡射原始碼結構。
- Run tests: `pytest -q` (add `-k <pattern>` to filter).
- Aim for critical-path coverage in `core/` and `services/` modules.

## Commit & Pull Request Guidelines
- Commits: imperative mood, concise scope prefix when helpful, e.g. `core: add rate limiter`.
- Include why + what changed; group related changes.
- PRs: clear description, linked issues, repro steps, and screenshots for UI.
- CI/readiness: ensure app starts locally and tests/lint pass before requesting review.

## Security & Configuration
- Never commit real secrets. Use `.env` locally and keep examples in `.env.production.example`.
- Validate all external inputs at service boundaries.
- Review `render.yaml` changes for least-privilege and environment parity.

## Agent-Specific Instructions
- 語言與語氣：全程使用繁體中文（台灣口吻），先給結論再補細節；可微嗆但不冒犯。
- TDD 原則：先寫測試（紅燈）→ 最小實作（綠燈）→ 重構；每個功能至少跑完一輪。
- Python 與 OpenAI：使用 Python3；OpenAI 一律 `gpt-4o-mini` 並透過 MCP 協議呼叫；程式碼中禁止使用命令參數。
- 測試放置：所有測試集中於 `tests/` 資料夾，檔名 `test_*.py`，結構鏡射模組路徑。
