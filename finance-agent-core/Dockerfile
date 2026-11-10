ARG PYTHON_IMAGE=python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60
FROM ${PYTHON_IMAGE} AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libpq5 libgomp1 libstdc++6 tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH" \
    HF_BAKED_CACHE=/opt/hf-cache-baked \
    HF_HOME=/opt/hf-cache-baked \
    HF_HUB_CACHE=/opt/hf-cache-baked/hub \
    SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache-baked/hub \
    FASTEMBED_CACHE_PATH=/opt/hf-cache-baked/hub

FROM base AS dependencies
ARG UV_VERSION=0.13.6
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=via-uv-py311,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-install-project
RUN --mount=type=cache,id=via-uv-py311,target=/root/.cache/uv,sharing=locked \
    uv pip install --python /opt/venv/bin/python \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "${arch}" in \
        amd64) supercronic="supercronic-linux-amd64"; supercronic_sha1="bc072eba2ae083849d5f86c6bd1f345f6ed902d0" ;; \
        arm64) supercronic="supercronic-linux-arm64"; supercronic_sha1="37842646e4c95b193c469afae400966565c383d3" ;; \
        *) echo "unsupported architecture: ${arch}" >&2; exit 1 ;; \
    esac; \
    supercronic_url="https://github.com/aptible/supercronic/releases/download/v0.2.38/${supercronic}"; \
    curl -fsSLo "/tmp/${supercronic}" "${supercronic_url}"; \
    echo "${supercronic_sha1}  /tmp/${supercronic}" | sha1sum -c -; \
    chmod +x "/tmp/${supercronic}"; \
    mv "/tmp/${supercronic}" "/usr/local/bin/${supercronic}"; \
    ln -sf "/usr/local/bin/${supercronic}" /usr/local/bin/supercronic

FROM dependencies AS model-artifacts
ARG BAKE_HF_MODELS=1
COPY scripts/bake_models.py /tmp/bake_models.py
RUN BAKE_HF_MODELS="${BAKE_HF_MODELS}" python /tmp/bake_models.py

FROM base AS runtime
COPY --from=dependencies /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/
COPY --from=dependencies /usr/local/bin/supercronic /usr/local/bin/supercronic
COPY --from=dependencies /opt/venv /opt/venv
COPY --from=model-artifacts /opt/hf-cache-baked /opt/hf-cache-baked
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && sed -i 's/\r$//' /usr/local/bin/entrypoint.sh
COPY . .
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Select explicitly when an in-container development task compiles extensions.
FROM runtime AS development
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

FROM runtime AS default
