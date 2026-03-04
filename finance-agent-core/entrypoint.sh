#!/bin/bash
set -e

# Function to wait for a port
wait_for_port() {
    local host="$1"
    local port="$2"
    local timeout="${3:-30}"
    local count=0

    echo "Waiting for $host:$port..."
    until python3 -c "import socket; s = socket.socket(); s.connect(('$host', $port))" > /dev/null 2>&1; do
        sleep 1
        count=$((count + 1))
        if [ $count -ge $timeout ]; then
            echo "Timeout waiting for $host:$port"
            exit 1
        fi
    done
    echo "$host:$port is ready!"
}

seed_hf_cache() {
    local runtime_cache="${HF_HOME:-/opt/hf-cache}"
    local baked_cache="${HF_BAKED_CACHE:-/opt/hf-cache-baked}"

    if [ ! -d "$baked_cache" ]; then
        return
    fi

    mkdir -p "$runtime_cache"
    if [ -z "$(ls -A "$runtime_cache" 2>/dev/null)" ]; then
        echo "Seeding Hugging Face cache from baked image layer..."
        cp -a "${baked_cache}/." "${runtime_cache}/"
    else
        # Keep runtime cache fresh when image adds new baked models.
        # `cp -an` copies only missing paths/files and preserves existing cache artifacts.
        echo "Syncing missing Hugging Face cache entries from baked image layer..."
        cp -an "${baked_cache}/." "${runtime_cache}/"
    fi

    export HF_HUB_CACHE="${HF_HUB_CACHE:-${runtime_cache}/hub}"
    export SENTENCE_TRANSFORMERS_HOME="${SENTENCE_TRANSFORMERS_HOME:-${HF_HUB_CACHE}}"
    export FASTEMBED_CACHE_PATH="${FASTEMBED_CACHE_PATH:-${HF_HUB_CACHE}}"
    mkdir -p "${FASTEMBED_CACHE_PATH}"
    # transformers v5 deprecates TRANSFORMERS_CACHE in favor of HF_HOME.
    unset TRANSFORMERS_CACHE
}

seed_hf_cache

# Wait for Postgres and Redis if environment variables are set
if [ -n "$POSTGRES_HOST" ]; then
    wait_for_port "$POSTGRES_HOST" "${POSTGRES_PORT:-5432}"
fi

if [ -n "$REDIS_HOST" ]; then
    wait_for_port "$REDIS_HOST" "${REDIS_PORT:-6379}"
fi

# Run the application
echo "Starting backend..."
cd /app
# Use the isolated virtualenv
export PATH="/opt/venv/bin:$PATH"
export PYTHONPATH="/app:/app/src:$PYTHONPATH"
exec python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
