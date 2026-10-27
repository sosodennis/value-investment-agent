# Model artifact and cache lifecycle

The image is the authoritative owner of pinned Hugging Face artifacts. The
default Compose mode reads those immutable artifacts in place and starts
without Hugging Face registry access. A writable runtime cache is an explicit
opt-in for workflows that download additional artifacts or need cache contents
to survive image replacement.

## Ownership

| Mode | Artifact source | Runtime path | Persistent model volumes | Intended use |
| --- | --- | --- | --- | --- |
| Default | Pinned artifacts baked into each service image at build time | `/opt/hf-cache-baked` | None | Normal development, staging, and production-like verification |
| Runtime cache | Baked image seeds missing files into a writable cache | `/opt/hf-cache` | `<project>_hf_cache`, `<project>_inference_news_hf_cache`, `<project>_inference_fls_hf_cache` | Explicit workflows that need runtime downloads or persistence across image replacement |

The backend owns the embedding artifacts in its image. The News and SEC FLS
inference images each own their pinned classifier artifact. `HF_HOME`,
`HF_HUB_CACHE`, and the service-specific cache variables point into the baked
path by default, and the Compose environment sets the Hugging Face offline and
local-only flags. Model downloads happen during an image build when the baked
cache layer is missing; running a built image does not require registry access.

The optional `docker-compose.runtime-cache.yml` changes only the runtime cache
paths and mounts three Compose-managed, project-scoped volumes. The entrypoints
copy baked files into an empty cache and add only missing files on later
starts. This mode intentionally stores a second copy of baked artifacts.
Compose volume names and labels identify the owning project; do not give these
volumes a shared custom name or mount them into another worktree.

## Start and restart

Choose a unique Compose project for each worktree and keep `.env` local to that
worktree. Validate and start the default mode with:

```sh
PROJECT=value-investment-agent-dev-feature
docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.override.yml config --quiet
docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.override.yml up -d --build
docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.override.yml ps
```

The default mode must not create the three named model cache volumes. Restart
or recreate a service normally; its model files remain in the image:

```sh
docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.override.yml restart model-inference-news model-inference-fls
```

Select writable runtime caches only by adding the override explicitly:

```sh
docker compose -p "$PROJECT" \
  -f docker-compose.yml \
  -f docker-compose.override.yml \
  -f docker-compose.runtime-cache.yml config --quiet
docker compose -p "$PROJECT" \
  -f docker-compose.yml \
  -f docker-compose.override.yml \
  -f docker-compose.runtime-cache.yml up -d --build
```

The runtime cache volumes survive service recreation and `docker compose down`
without `--volumes`. Rebuilding an image does not discard user-downloaded
runtime files; the entrypoint copies any missing baked files on the next
container start. Because baked files are duplicated, measure image and volume
usage separately with `docker system df -v` before and after testing this mode.

## Health and offline behavior

Check service health and the loaded model revision after startup or restart:

```sh
docker compose -p "$PROJECT" ps
docker compose -p "$PROJECT" exec -T model-inference-news python -c 'import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("http://localhost:8001/readyz/details")), sort_keys=True))'
docker compose -p "$PROJECT" exec -T model-inference-fls python -c 'import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("http://localhost:8001/readyz/details")), sort_keys=True))'
```

Readiness must report the expected pinned model revision. For behavioral
verification, send a valid authenticated `news.sentiment` request and a valid
`sec.fls` request to `/v1/inference`; verify the response operation, result
shape, correlation ID, and model revision. The service contract and real
endpoint checks are documented in
[`model-inference-rollout.md`](model-inference-rollout.md).

## Retire a worktree

Stop only the retired project's containers and network. This keeps PostgreSQL,
Redis, and model cache volumes in place while they are inspected:

```sh
docker compose -p "$PROJECT" down
```

Preview the exact HF cache volumes, Compose ownership labels, mounted-container
references, size, and top-level contents. Preview is the default and does not
delete anything. The helper uses the already available `alpine:3.20` image as
a read-only inspector and will fail closed if that image is absent:

```sh
python3 scripts/docker/cleanup_retired_model_cache_volumes.py --project "$PROJECT"
```

After confirming the project is retired and the preview contains only
disposable HF cache data, remove those exact three cache volume names:

```sh
python3 scripts/docker/cleanup_retired_model_cache_volumes.py \
  --project "$PROJECT" --confirm-retired
```

The helper refuses a project with any remaining container, refuses a cache
volume mounted by any container, verifies Compose project and logical-volume
labels, and removes only the three allowlisted model cache volumes. It never
removes PostgreSQL or Redis volumes, images, containers, networks, or BuildKit
cache. Missing cache volumes are skipped, so cleanup is repeatable. Do not use
`docker volume prune`, `docker system prune --volumes`, or
`docker compose down --volumes` for this lifecycle.
