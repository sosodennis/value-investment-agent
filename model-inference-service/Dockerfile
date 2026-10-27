FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    HF_BAKED_CACHE=/opt/hf-cache-baked \
    HF_HOME=/opt/hf-cache \
    HF_HUB_CACHE=/opt/hf-cache/hub \
    TRANSFORMERS_CACHE=/opt/hf-cache/hub

COPY pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.11.28 \
    && uv sync --frozen --no-dev --extra models --no-install-project

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

COPY src ./src
COPY --from=internal-contracts . /app/src/shared
RUN uv sync --frozen --no-dev --extra models

COPY entrypoint.sh /usr/local/bin/model-inference-entrypoint.sh
RUN chmod +x /usr/local/bin/model-inference-entrypoint.sh

# The default runtime reads the immutable model artifact baked into the image.
# A separate Compose override can opt into a writable runtime cache.
ENV HF_HOME=/opt/hf-cache-baked \
    HF_HUB_CACHE=/opt/hf-cache-baked/hub \
    TRANSFORMERS_CACHE=/opt/hf-cache-baked/hub

EXPOSE 8001
ENTRYPOINT ["/usr/local/bin/model-inference-entrypoint.sh"]
