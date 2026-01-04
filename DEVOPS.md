# DevOps Manual: Value Investment Agent

This guide covers how to manage the containerized application using Docker Compose.

## 🚀 Quick Start

1.  **Environment Variables**: Ensure you have a `.env` file in the root directory (or appropriate places) with your API keys:
    ```env
    OPENAI_API_KEY=your_key
    TAVILY_API_KEY=your_key
    ```

2.  **Start All Services**:
    ```bash
    docker-compose up -d
    ```

3.  **Access**:
    - Frontend: [http://localhost:3000](http://localhost:3000)
    - Backend API: [http://localhost:8000](http://localhost:8000)
    - Adminer (Optional, if added): [http://localhost:8080](http://localhost:8080)

## 📋 Common Operations

### View Logs
To follow logs for all services:
```bash
docker-compose logs -f
```

To see logs for a specific service:
```bash
docker-compose logs -f backend
docker-compose logs -f frontend
```

### Restart Services
Restart everything:
```bash
docker-compose restart
```

Restart a specific service:
```bash
docker-compose restart backend
```

### Rebuild and Start
If you changed dependencies or the Dockerfile:
```bash
docker-compose up -d --build
```

### Stop All Services
```bash
docker-compose down
```
To also remove volumes (WARNING: This deletes your database data!):
```bash
docker-compose down -v
```

## 💾 Persistence & Volumes

- **PostgreSQL Data**: Stored in the `pg_data` docker volume.
- **Redis Data**: Stored in the `redis_data` docker volume.
- **Backend Code**: The `backend` service uses a bind mount (`./finance-agent-core:/app`) for development, allowing hot-reloads if uvicorn is configured with `--reload`.

## 🔍 Debugging

1.  **Database Connection**:
    ```bash
    docker-compose exec postgres psql -U postgres -d langgraph
    ```

2.  **Redis Check**:
    ```bash
    docker-compose exec redis redis-cli ping
    ```

3.  **Shell Access**:
    ```bash
    docker-compose exec backend bash
    ```

## 🛠 Troubleshooting

- **Port Conflicts**: If port 8000, 3000, 5432, or 6379 is already in use on your host, you may need to change the mappings in `docker-compose.yml`.
- **Environment Variables**: Make sure the `.env` file is in the same directory as `docker-compose.yml`.
