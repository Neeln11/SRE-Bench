FROM python:3.11-slim

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy metadata for caching
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the source
COPY . .

# HuggingFace Spaces uses port 7860
EXPOSE 7860

# Healthcheck against consolidated app (port 7860)
# We use uv run to ensure we use the virtualenv
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD uv run python -c "import requests; requests.get('http://localhost:7860/health', timeout=5)"

# Entry point using uv run to ensure the virtualenv is active
CMD ["uv", "run", "python", "main.py"]
