ARG PYTHON_IMAGE=python:3.11-slim@sha256:673719e071ecf27434fd2635bbd8d00f49f4fdd81f243143438a42ced8bedf60
FROM ${PYTHON_IMAGE} AS base
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}" \
    HF_BAKED_CACHE=/opt/hf-cache-baked \
    HF_HOME=/opt/hf-cache-baked \
    HF_HUB_CACHE=/opt/hf-cache-baked/hub \
    TRANSFORMERS_CACHE=/opt/hf-cache-baked/hub

FROM base AS dependencies
ARG UV_VERSION=0.11.28
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=via-uv-py311,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --extra models --no-install-project

FROM dependencies AS model-artifacts
ARG BAKE_HF_MODELS=1
ARG INFERENCE_OPERATIONS=news.sentiment,sec.fls
ARG NEWS_FINBERT_MODEL=project-aps/finbert-finetune
ARG NEWS_FINBERT_REVISION=2db55b5439cef6253c12a4973f3a9e823ff90b79
ARG SEC_FLS_MODEL=yiyanghkust/finbert-fls
ARG SEC_FLS_REVISION=443586dc31c765c0aaf1c4daaed8cf3643c92fa5
COPY scripts/bake_models.py /tmp/bake_models.py
RUN mkdir -p "${HF_BAKED_CACHE}" \
    && if [ "${BAKE_HF_MODELS}" = "1" ]; then \
      HF_HOME="${HF_BAKED_CACHE}" HF_HUB_CACHE="${HF_BAKED_CACHE}/hub" \
      INFERENCE_OPERATIONS="${INFERENCE_OPERATIONS}" \
      NEWS_FINBERT_MODEL="${NEWS_FINBERT_MODEL}" NEWS_FINBERT_REVISION="${NEWS_FINBERT_REVISION}" \
      SEC_FLS_MODEL="${SEC_FLS_MODEL}" SEC_FLS_REVISION="${SEC_FLS_REVISION}" \
      python /tmp/bake_models.py; \
    fi

FROM base AS runtime
COPY --from=dependencies /usr/local/bin/uv /usr/local/bin/uvx /usr/local/bin/
COPY --from=dependencies /app/.venv /app/.venv
COPY --from=model-artifacts /opt/hf-cache-baked /opt/hf-cache-baked
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY --from=internal-contracts . /app/src/shared
RUN --mount=type=cache,id=via-uv-py311,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --extra models
COPY entrypoint.sh /usr/local/bin/model-inference-entrypoint.sh
RUN chmod +x /usr/local/bin/model-inference-entrypoint.sh
EXPOSE 8001
ENTRYPOINT ["/usr/local/bin/model-inference-entrypoint.sh"]
