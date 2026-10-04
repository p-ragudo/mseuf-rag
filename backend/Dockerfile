# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

# 1. Install base OS build and database packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# 2. Grab the uv binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 3. Copy requirements first to leverage Docker layer caching
COPY requirements.txt ./

# 4. Install all Python dependencies via uv directly to system site-packages
RUN uv pip install -r requirements.txt

# 5. Install Crawl4AI Playwright browser binaries and system libs
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium

# 6. Copy the rest of the backend codebase
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]