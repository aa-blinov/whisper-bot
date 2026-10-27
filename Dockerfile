FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim

# ffmpeg — декодирование OGG/Opus и MP4-кружков, libsndfile — WAV/FLAC,
# libgomp1 — OpenMP для onnxruntime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

COPY app/ ./app/
# Тестовые образцы для scripts/smoke_flow.py: они маленькие и должны быть
# в образе, иначе проверка на чистом клоне пропускает распознавание.
COPY tests/ ./tests/

# Кэш моделей живёт в томе ./data:/app/data.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/data/hf \
    HF_HUB_DISABLE_TELEMETRY=1

RUN mkdir -p /app/data/hf && chmod -R 777 /app/data

CMD ["python", "-m", "app.main"]
