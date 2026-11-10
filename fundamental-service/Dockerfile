ARG PYTHON_IMAGE=python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    FUNDAMENTAL_SERVICE_DATA_ROOT=/var/lib/fundamental
WORKDIR /app

FROM base AS dependencies
RUN python -m pip install --no-cache-dir uv==0.13.6
COPY fundamental-service/pyproject.toml fundamental-service/uv.lock fundamental-service/README.md ./
RUN --mount=type=cache,id=via-uv-py312,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project

FROM base AS runtime
RUN useradd --create-home --uid 10001 fundamental \
    && mkdir -p /var/lib/fundamental \
    && chown fundamental:fundamental /var/lib/fundamental
COPY --from=dependencies /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/
COPY --from=dependencies --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 fundamental-service/pyproject.toml fundamental-service/uv.lock fundamental-service/README.md ./
COPY --chown=10001:10001 --from=internal-contracts internal_services ./src/shared/internal_services
COPY --chown=10001:10001 fundamental-service/src ./src
RUN --mount=type=cache,id=via-uv-py312,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev
USER fundamental
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=2)"
STOPSIGNAL SIGTERM
CMD ["uvicorn", "fundamental_service.app:app", "--host", "0.0.0.0", "--port", "8080"]
