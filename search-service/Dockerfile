FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml ./
RUN python -m pip install --no-cache-dir uv==0.11.28 \
    && uv sync --no-dev --no-install-project

COPY --from=internal-contracts internal_services ./src/shared/internal_services
COPY src ./src/search_service
RUN uv sync --no-dev

EXPOSE 8003
CMD ["uvicorn", "src.search_service.app:app", "--host", "0.0.0.0", "--port", "8003"]
