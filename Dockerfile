FROM python:3.12.3-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/cache \
    MPLCONFIGDIR=/tmp/matplotlib \
    NUMBA_CACHE_DIR=/tmp/numba_cache \
    SPEECHBRAIN_CACHE_DIR=/tmp/speechbrain_cache \
    HF_HOME=/tmp/huggingface_cache \
    TRANSFORMERS_CACHE=/tmp/transformers_cache

WORKDIR /app

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
    && pip install --no-cache-dir --prefer-binary -r requirements.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p ${XDG_CACHE_HOME}/fontconfig ${MPLCONFIGDIR} ${NUMBA_CACHE_DIR} ${SPEECHBRAIN_CACHE_DIR} ${HF_HOME} ${TRANSFORMERS_CACHE}

COPY . .

ENV PORT=7860

CMD ["bash", "-lc", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
