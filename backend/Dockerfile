# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Avoid prompts and ensure unbuffered stdout/stderr logging
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=0 \
    UV_LINK_MODE=copy

# Install essential system dependencies, build tools, and SSL certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv from the official Astral binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency specifications first to leverage Docker layer caching
COPY pyproject.toml uv.lock ./

# Install project dependencies into the virtual environment (.venv)
RUN uv sync --frozen --no-install-project

# Install Playwright browser dependencies required by Crawl4AI
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN . .venv/bin/activate && \
    python -m playwright install --with-deps chromium

# Copy application source code
COPY . .

# Final sync to install the current project package in editable/wheel mode
RUN uv sync --frozen

# Ensure the virtualenv's binaries are primary in PATH
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Default command launches FastAPI via uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]