FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FUNDAMENTAL_SERVICE_DATA_ROOT=/var/lib/fundamental

WORKDIR /app

COPY fundamental-service/pyproject.toml fundamental-service/uv.lock fundamental-service/README.md ./
COPY --from=internal-contracts internal_services ./src/shared/internal_services
COPY fundamental-service/src ./src

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 fundamental \
    && mkdir -p /var/lib/fundamental \
    && chown -R fundamental:fundamental /app /var/lib/fundamental

USER fundamental
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=2)"

STOPSIGNAL SIGTERM
CMD ["uvicorn", "fundamental_service.app:app", "--host", "0.0.0.0", "--port", "8080"]
