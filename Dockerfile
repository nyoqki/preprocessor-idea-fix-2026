# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.12.21 AS uv

FROM node:22-alpine AS webapp
WORKDIR /webapp
RUN --mount=type=cache,target=/root/.npm \
    --mount=type=bind,source=webapp/package.json,target=package.json \
    --mount=type=bind,source=webapp/package-lock.json,target=package-lock.json \
    --mount=type=bind,source=webapp/.npmrc,target=.npmrc \
    npm ci --no-audit --no-fund
COPY webapp ./
RUN npm run build

FROM python:3.13-slim AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY pyproject.toml uv.lock README.md* ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.13-slim AS runtime
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /data/storage \
    && chown -R app:app /data
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=webapp /webapp/dist /app/webapp
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STORAGE_DIR=/data/storage \
    WEBAPP_DIST_DIR=/app/webapp
WORKDIR /app
USER app
EXPOSE 8000
ENTRYPOINT ["yasno"]
CMD ["api"]
