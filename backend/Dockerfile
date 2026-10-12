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
# Optionally bake the BioBERT clinical NLP model too (about 430 MB; used when CLINICAL_NLP_ENABLED=true).
ARG PRELOAD_CLINICAL_NLP=false
RUN if [ "$PRELOAD_CLINICAL_NLP" = "true" ]; then \
      python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb')"; \
    fi

COPY . .
RUN python -m scripts.make_synthetic_protocol \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/data \
    && chown -R app:app /app
USER app

ENV DATA_DIR=/app/data \
    PORT=8000 \
    WEB_CONCURRENCY=1
EXPOSE 8000
VOLUME ["/app/data"]

# One worker by default: the file store and in-memory workflow state are per process. With DATABASE_URL
# and REDIS_URL set, WEB_CONCURRENCY can be raised because all state is shared.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
