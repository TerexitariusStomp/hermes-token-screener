FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir \
    pydantic pydantic-settings structlog prometheus-client rich httpx \
    fastapi uvicorn

COPY hermes_screener/ hermes_screener/

VOLUME ["/root/.hermes/data", "/root/.hermes/logs"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["uvicorn", "hermes_screener.dashboard.app:app", "--host", "0.0.0.0", "--port", "8080"]
