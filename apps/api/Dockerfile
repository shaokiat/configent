FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install deps before copying app code (better layer cache)
WORKDIR /workspace/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev

# Copy the Python package
COPY apps/api/ ./

# Copy repo-level assets the API needs at runtime
WORKDIR /workspace
COPY config/ config/
COPY prompts/ prompts/
COPY assets/ assets/

WORKDIR /workspace/apps/api

EXPOSE 8000

# Run migrations then start the server
CMD ["sh", "-c", ".venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"]
