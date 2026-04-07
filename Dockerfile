FROM python:3.11-slim-bookworm

WORKDIR /app

# Copy requirements file first for layer caching
COPY requirements.txt .

# Install dependencies globally via pip for compatibility with all scripts
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source code
COPY . .

# HuggingFace Spaces uses port 7860
EXPOSE 7860

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:7860/health', timeout=5)"

# Entry point
CMD ["python", "main.py"]
