FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY hermes_screener/ hermes_screener/
COPY scripts/ scripts/

# Create directories for data
RUN mkdir -p /app/.hermes/data /app/.hermes/logs

# Set environment variables
ENV HERMES_HOME=/app
ENV PYTHONPATH=/app
ENV PORT=8080

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Start command
CMD ["uvicorn", "hermes_screener.dashboard.app:app", "--host", "0.0.0.0", "--port", "8080"]
