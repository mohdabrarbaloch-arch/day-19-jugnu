# syntax=docker/dockerfile:1

# ---------- build stage ----------
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Build deps for lxml and psycopg wheels that need compiling.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

# ---------- runtime stage ----------
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# libxml2/libxslt runtime libs for lxml; curl for the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 libxslt1.1 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 jugnu

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=jugnu:jugnu app ./app
COPY --chown=jugnu:jugnu pyproject.toml README.md ./

USER jugnu

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
