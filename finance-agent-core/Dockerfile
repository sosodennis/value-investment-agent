# Use Python 3.11 slim as base
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    libpq-dev \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Enable venv in a separate location to avoid bind-mount interference
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV HF_BAKED_CACHE=/opt/hf-cache-baked
ENV HF_HOME=/opt/hf-cache
ENV HF_HUB_CACHE=/opt/hf-cache/hub
ENV SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache/hub
ENV FASTEMBED_CACHE_PATH=/opt/hf-cache/hub

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen --no-dev --no-install-project

# Install spaCy dependency model used by the dependency matcher layer.
# Use uv pip directly to avoid relying on pip being bundled in the venv.
RUN uv pip install --python /opt/venv/bin/python \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# Pre-bake Hugging Face models into image layer.
# Runtime cache may be bind-mounted; entrypoint will seed from this baked cache.
RUN mkdir -p "${HF_BAKED_CACHE}" "${HF_HOME}"
RUN HF_HOME="${HF_BAKED_CACHE}" \
    HF_HUB_CACHE="${HF_BAKED_CACHE}/hub" \
    SENTENCE_TRANSFORMERS_HOME="${HF_BAKED_CACHE}/hub" \
    python - <<'PY'
from huggingface_hub import snapshot_download

model_repos = [
    "project-aps/finbert-finetune",
    "yiyanghkust/finbert-fls",
    "sentence-transformers/all-MiniLM-L6-v2",
    "qdrant/all-MiniLM-L6-v2-onnx",
]

for repo_id in model_repos:
    print(f"Pre-downloading Hugging Face repo: {repo_id}", flush=True)
    snapshot_download(repo_id=repo_id)
PY

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

# Copy entrypoint separately to avoid being overwritten by bind mount
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && sed -i 's/\r$//' /usr/local/bin/entrypoint.sh

# Copy the rest of the application code
COPY . .

# Expose the API port
EXPOSE 8000

# Use entrypoint script
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
