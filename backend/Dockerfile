# Three stages: `base` (Python + Stockfish + runtime deps), `prod` (what gets deployed: code copied in,
# non-root user) and `dev` (adds test/lint tools; the compose dev setup mounts the source over /app).
# The LAST stage is the default build target, so a plain `docker build` produces the dev image.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Stockfish (GPL-3.0) is installed from the distro, not vendored in the repo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt


FROM base AS prod
COPY . .
# Nothing here needs root. Stockfish and the app only read their files.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER app


FROM base AS dev
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
