FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

COPY llm-provider-service/pyproject.toml ./
RUN python -m pip install --no-cache-dir uv==0.11.28 \
    && uv sync --no-dev --no-install-project

COPY finance-agent-core/src/shared/internal_services ./src/shared/internal_services
COPY llm-provider-service/src ./src/llm_provider_service
RUN uv sync --no-dev

EXPOSE 8002
CMD ["uvicorn", "src.llm_provider_service.app:app", "--host", "0.0.0.0", "--port", "8002"]
