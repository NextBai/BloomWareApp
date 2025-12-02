FROM python:3.12.3-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    NUMBA_CACHE_DIR=/tmp/numba_cache

WORKDIR /app

# 安裝系統依賴（包含 Node.js）
COPY requirements.txt ./
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        libfreetype6-dev \
        libpng-dev \
        libjpeg-dev \
        libopenblas-dev \
        liblapack-dev \
        libsndfile1 \
        ffmpeg \
        libasound2-dev \
        portaudio19-dev \
        curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && pip install --no-cache-dir --prefer-binary -r requirements.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p ${XDG_CACHE_HOME}/fontconfig \
    ${MPLCONFIGDIR} \
    ${NUMBA_CACHE_DIR} \
    /tmp/voice_cache \
    && chmod -R 777 ${XDG_CACHE_HOME} \
    && chmod -R 777 ${MPLCONFIGDIR} \
    && chmod -R 777 ${NUMBA_CACHE_DIR} \
    && chmod -R 777 /tmp/voice_cache

COPY . .

# Build Next.js 前端
RUN cd bloom-ware-login \
    && echo "=== 檢查檔案結構 ===" \
    && ls -la lib/ \
    && echo "=== 檢查 tsconfig.json ===" \
    && cat tsconfig.json | grep -A 5 "paths" \
    && npm install --legacy-peer-deps \
    && echo "=== 使用 webpack 建置（禁用 Turbopack） ===" \
    && NEXT_USE_TURBOPACK=0 npm run build \
    && cd ..

ENV PORT=7860

CMD ["bash", "-lc", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
