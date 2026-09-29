# --- Frontend build stage ---
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- Backend runtime stage ---
FROM python:3.12-slim AS runtime

# asyncpg ships wheels; no build tooling needed on slim.
RUN useradd --create-home --uid 1000 inspector
WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
RUN pip install --no-cache-dir .

# Built SPA is served by FastAPI (single origin in production).
COPY --from=frontend-build /build/dist ./static

USER inspector
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Migrations run before the API starts; one worker because the rate limiter
# and the SSE broker are in-process (documented limitation).
ENTRYPOINT ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
