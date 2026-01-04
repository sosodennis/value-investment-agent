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
