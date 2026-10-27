# Multi-stage build for TraceFix single-container deployment

# Stage 1: Build Frontend Assets
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Python Backend Runtime
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app

# Install git (required for repository inspection and worktree management)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy Python package specifications & source, then install package
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN uv pip install --system --no-cache .

# Copy repository data, contracts, and snapshot artifacts
COPY data/repos/requests/ ./data/repos/requests/
COPY artifacts/ ./artifacts/
COPY eval/ ./eval/
COPY contracts/ ./contracts/
COPY docs/experiments/ ./docs/experiments/

# Copy built frontend assets into frontend/dist
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Non-root user for security
RUN useradd -m -u 1000 tracefix && chown -R tracefix:tracefix /app
USER tracefix

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:' + str(os.environ.get('PORT', 8000)) + '/api/health')" || exit 1

CMD ["sh", "-c", "uvicorn tracefix.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]

