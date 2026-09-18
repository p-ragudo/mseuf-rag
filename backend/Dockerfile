FROM mcr.microsoft.com/playwright/python:v1.49.0-noble

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependency definitions first for layer caching
COPY pyproject.toml uv.lock* ./

# Install project dependencies
RUN uv sync --frozen --no-cache

# Ensure Chromium browser binaries are installed
RUN uv run playwright install chromium

# Copy application source code
COPY . .

# Expose internal FastAPI port
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]