FROM python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60 AS build

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.13.6 \
    && uv sync --frozen --no-dev --no-install-project

COPY --from=internal-contracts internal_services ./src/shared/internal_services
COPY src/llm_provider_service ./src/llm_provider_service
RUN uv sync --frozen --no-dev

FROM python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# The application runs from its isolated /app/.venv. Remove the base image's
# installer toolchain from the runtime layer so build-only packages are not
# shipped with the service image.
RUN rm -rf /usr/local/lib/python3.11/site-packages/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src ./src

EXPOSE 8002
CMD ["uvicorn", "src.llm_provider_service.app:app", "--host", "0.0.0.0", "--port", "8002"]
