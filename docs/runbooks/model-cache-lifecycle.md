# Model artifact storage lifecycle

## Authoritative storage

The default Compose stack treats model artifacts as immutable image content. Model snapshots are downloaded into `/opt/hf-cache-baked` during image build, and `HF_HOME`, `HF_HUB_CACHE`, `TRANSFORMERS_CACHE`, and service-specific cache variables point at that path at runtime. The default stack declares no Hugging Face named volumes. Startup therefore reads the image copy directly, including when Hugging Face offline flags are enabled.

Builds and image replacement own the baked artifact lifecycle: a rebuilt image contains the pinned snapshot selected by its model and revision build arguments. Container restart or recreation reuses that image content without copying weights into a writable layer or volume. Removing a container does not affect model availability while its image remains available; removing the image releases its uniquely unreferenced image layers subject to Docker's shared layer accounting.

## Writable cache exception

`docker-compose.runtime-cache.yml` is opt-in for workflows that need runtime downloads or persistence across image replacement. It redirects cache variables to `/opt/hf-cache` and declares three project-scoped volumes. The entrypoints seed missing files from the baked cache, so this mode intentionally duplicates baked artifacts in each volume. Do not use this profile for ordinary offline startup.

## Worktree retirement

Every worktree must use a unique Compose project name. To retire a worktree using the writable-cache profile:

1. Stop and remove its containers and network while preserving volumes: `docker compose -p <project> down`.
2. From that worktree checkout, run `scripts/docker/retire-worktree-model-caches.sh <project>`.

The helper refuses projects outside the `value-investment-agent-*` namespace and refuses cleanup while any project container exists, including stopped containers. It removes only volumes carrying both the selected Compose project label and one of the explicit `hf_cache`, `inference_news_hf_cache`, or `inference_fls_hf_cache` volume labels. It does not remove Postgres/Redis data, images, networks, or any other project's volumes. Running it again is harmless.

The default stack has no model cache volumes, so the helper reports zero removals. `docker compose down` without `--volumes` remains the normal way to stop a worktree whose database state must be retained. Do not use global prune commands for worktree retirement.
