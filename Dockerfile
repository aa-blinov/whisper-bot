FROM python:3.10.18-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu

FROM python:3.10.18-slim AS app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

COPY app/ .

RUN mkdir -p /app/data

CMD ["python", "-u", "bot.py"]