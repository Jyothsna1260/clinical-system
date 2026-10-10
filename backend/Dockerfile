FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Bake the embedding model into the image so the first analysis does not download it.
ARG PRELOAD_EMBEDDINGS=true
RUN if [ "$PRELOAD_EMBEDDINGS" = "true" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"; \
    fi

COPY . .
RUN python -m scripts.make_synthetic_protocol \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/data \
    && chown -R app:app /app
USER app

ENV DATA_DIR=/app/data \
    PORT=8000
EXPOSE 8000
VOLUME ["/app/data"]

# One worker: the file store serializes writes within a single process.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
