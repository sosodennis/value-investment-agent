# Compose configuration

The root files describe the supported day-to-day stacks:

- `../docker-compose.yml` is the canonical service graph.
- `../docker-compose.override.yml` is the automatically loaded local-development override.
- `../docker-compose.production.yml` supplies production secrets and settings.
- `../docker-compose.runtime-cache.yml` is an explicit opt-in for writable model caches.

The `verification/` directory contains reproducible overlays for the closed
issue acceptance runs. They are kept separate from the normal startup path and
are used only by the verification scripts and runbooks.

Validate a selected stack before starting it:

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml config --quiet
```
