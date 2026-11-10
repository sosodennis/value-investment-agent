---
name: docker-development
description: Use this project guidance when configuring or running Docker Compose for local development, tests, or concurrent worktrees. Covers stack isolation, ports, state, builds, cache, and cleanup. Not for production deployment.
---

# Docker development

Use this skill before changing Compose configuration, starting or building a stack, running containerized tests, or cleaning Docker resources for this project.

## Storage changes without interrupting development

Use [the Docker storage runbook](../../../docs/runbooks/docker-storage.md) for
image slimming, model file selection, cache retention and rollout checks.
Validate candidate images under new tags and a new Compose project; preserve
existing projects' images, containers, networks, ports and data. Record existing
container IDs/image IDs/start times before and after validation. Serialize large
builds and cap disposable verification containers' CPU/memory.

- The backend's default runtime keeps installed packages and runtime libraries;
  compiler tools live in its explicit `development` target. Select
  `docker-compose.build-tools.yml` when an in-container task compiles extensions.
  Use the same overlay for backend and migrations so they share the selected image.
- Keep dependency/model installation before source copying. uv download caches
  use BuildKit cache mounts with `UV_LINK_MODE=copy`; do not copy those caches into
  final images. Fundamental uses `COPY --chown` rather than recursively chowning
  a dependency tree in another layer.
- Bake only files required by existing loaders at immutable revisions. Preserve
  SentenceTransformer and FastEmbed support, tokenizer/pooling metadata, offline
  refs and classifier shard indexes. Keep actual model-output regression checks;
  readiness alone cannot prove that filtering retained the needed artifacts.
- Pin Python base digests and uv versions deliberately. Base pins help layer reuse
  and input traceability, but unpinned OS package repositories still prevent a
  blanket claim of bit-for-bit reproducible image builds.
- Distinguish logical image sizes, shared layers, BuildKit cache, volumes and
  actual VM free space. Byte-identical layers are already deduplicated. Similar
  images built from different base layers can still consume separate storage.
- Keep useful shared build cache and inspect age/size before reclaiming it. Do
  not change daemon GC settings or restart Docker Desktop during other work.
- `scripts/cleanup-docker-images.sh` requires `DOCKER_CLEANUP_PROJECT` and filters
  by that exact Compose project label plus dangling status and age. Inspect all
  container references, including stopped containers, before deleting other tags
  or volumes. Back up retained volume data outside the Docker VM and verify it.

## Inspect the current stack

- Read the root `docker-compose.yml` and any Compose override files used by the task. The service and profile list can change, so derive it from the current files instead of relying on a remembered list.
- Run `docker compose config --quiet` to validate Compose configuration. Use `docker compose config --services` and `docker compose config --profiles` to inspect the current services and profiles.
- Start only the services and profiles needed for the task. Optional services still consume shared host resources when they run.
- The project currently uses profiles, environment-backed host ports, and Compose-managed named volumes. Keep those patterns when adding services.
- Keep `.env` and other developer-specific port overrides untracked. The root `.gitignore` already ignores `.env`.
- Do not print or paste resolved Compose configuration when it contains secrets. Use `config --quiet` for validation.
- Bind-mount source files only when the development workflow needs live host edits. Keep database files and large caches in Docker-managed volumes because Docker Desktop file sharing adds overhead.

### Model artifacts and runtime caches

- Inspect model-related `Dockerfile` steps and entrypoints together. A baked path such as `/opt/hf-cache-baked` plus a mounted runtime path such as `/opt/hf-cache` stores the same model twice when the entrypoint seeds the mount.
- Choose one artifact owner per stack. For pinned, offline models, prefer an image-only default: point `HF_HOME`, `HF_HUB_CACHE`, and any library-specific cache variables at the baked path and omit the model volume. This keeps startup deterministic and avoids a second copy in a named volume or writable container layer.
- Keep writable model caches in a separately named, explicitly selected Compose override. Document that this mode intentionally duplicates baked artifacts and is for workflows that need runtime downloads or persistence across image replacement.
- When assessing storage, measure image layers and volume contents independently. Use `docker history` or `docker image inspect`, `docker volume inspect`, and `docker system df -v`; removing a volume declaration does not save space if an entrypoint still copies the baked cache into a writable path.

## Isolate each worktree

Docker Compose uses a project name to group and name a stack's containers, networks, and default named volumes. On a shared Docker engine, give each concurrently running worktree a unique project name. Include the repository, developer or agent, and worktree in the name. Use lowercase letters, digits, dashes, or underscores, and start with a letter or digit.

Pass the same explicit `-p` value to every Compose command for that worktree. For example:

```sh
PROJECT=value-investment-agent-dev-feature-x
docker compose -p "$PROJECT" config --quiet
docker compose -p "$PROJECT" config --services
docker compose -p "$PROJECT" up -d --build
docker compose -p "$PROJECT" ps
```

Compose project names do not reserve host ports or create a storage quota. Assign a different host port to every published port in each active worktree. Use environment variables with defaults for published ports, such as `127.0.0.1:${API_HOST_PORT:-8000}:8000`. Update browser-facing URLs, callbacks, and CORS settings when they depend on those ports.

Keep mutable data separate by default. Compose named volumes are project-scoped unless the file sets a custom `name` or marks the volume `external`. Bind mounts can also point multiple worktrees at the same host directory. Check those declarations before assuming a database, cache, or uploaded file is isolated.

Share a stateful service only when the team has defined its namespace, ownership, credentials, migration rules, and cleanup policy. Keep those details in the Compose configuration or the service's development documentation. Do not rely on a developer's memory to prevent cross-worktree data changes.

Do not set a fixed `container_name` for a service that must run in multiple worktrees. Do not reuse a fixed custom volume, network, or image tag across worktrees unless sharing is intentional. Compose's default built image tag includes the project and service names. An explicit `image` value can override that isolation.

## Make acceptance runtime identity explicit

Before starting or resuming an acceptance run, record and re-read one runtime tuple containing the absolute worktree path, branch, exact commit SHA, application and Fundamental Compose project names, ordered Compose files and overlays, env-file paths, published host ports, service URLs, and browser session/tab identity. Keep credentials and the contents of env files out of the record. The tuple is invalid as soon as any project, port, env-file, overlay, or browser session changes.

Exact-commit acceptance rejects tracked changes and untracked paths by default. If a runtime-only Compose or artifact override must remain outside Git, list its exact relative path in `ALLOWED_UNTRACKED_PATHS` and record it with the tuple. That override is runtime input, not commit evidence, and must never be silently ignored.

Run `docker compose ... config --quiet` with the exact `--env-file` and ordered `-f` arguments recorded for each project. Do not validate one file set and start another. Derive browser URLs from `docker compose ... port <service> <container-port>` after the project is running. Open a fresh browser tab whenever the project or port changes; an old tab can continue to point at a previous runtime even after a reload.

SEC-backed Fundamental acceptance has an explicit dependency boundary. It must include `compose/verification/docker-compose.issue312-sec-ingestion.yml` together with the base operations file and the pinned taxonomy, EDGAR, XULE, and DQC artifact variables. `compose/verification/docker-compose.issue280-operations.yml` alone starts a service process but does not configure SEC identity resolution. Set `REQUIRE_SEC_IDENTITY_RESOLUTION=1` when running `scripts/acceptance_preflight.sh` so `/readyz` must report `capabilities.identity_resolution_configured=true`.

Treat process health and feature readiness as different checks. A container marked `healthy` only proves that its configured healthcheck succeeded. For acceptance, call the service contract endpoints and verify the required capability, data, or user workflow. For Fundamental, distinguish `identity_resolution_configured`, successful issuer `resolved`, snapshot readiness, and valuation readiness; one state must not be reported as another.

## Build with shared resources in mind

Compose project isolation separates runtime resources. Builds still use the selected BuildKit builder and the host's shared CPU, memory, and disk. BuildKit cache can be reused across worktrees, which avoids downloading or storing duplicate layers when inputs match.

- Keep build contexts small with `.dockerignore` files.
- Order Dockerfile steps so dependency files are copied before frequently changed source files.
- Use package-manager cache mounts where they are supported and safe for concurrent builds.
- Keep the build cache enabled. Use `--no-cache` only when diagnosing cache behavior or when a clean build is part of the test.
- Build only the changed services when practical. Serialize high-footprint builds when disk or memory is under pressure.
- Check current use with `docker system df -v` and `docker buildx du --verbose`. Check the selected builder with `docker buildx ls` before pruning its cache.

Docker Desktop's disk usage limit caps storage for the shared Docker VM. It is not a quota for this repository or a Compose project. Build cache, images, writable container layers, and volumes all consume that shared storage. Docker Desktop's BuildKit garbage collection controls build cache only. The Docker documentation lists a 20 GB default cache target for the default Docker Desktop builder. Changing that target affects every project using that builder.

Leave automatic BuildKit garbage collection enabled. Build cache is shared by every project that uses the selected builder, so pruning it can make other developers' builds slower. If cache use needs a manual reduction, inspect the selected builder first and use an age or size limit that the team has agreed on. For example, `docker buildx prune --filter "until=168h" --max-used-space 20gb` targets the selected builder's cache and prompts before deleting it. Cache pruning does not remove database volumes.

## Stop and clean up safely

Use the worktree's project name when stopping its stack:

```sh
docker compose -p "$PROJECT" ps
docker compose -p "$PROJECT" down
```

`docker compose down` removes that project's containers and networks. It keeps named volumes unless you pass `--volumes`. Use named volumes for data that must survive container replacement. Anonymous volumes do not have stable names and Compose does not automatically remount them on a later `up`.

Do not run `docker volume prune` or `docker system prune --volumes` on a shared Docker engine. Do not run `docker compose down --volumes` until you have confirmed the project name and verified that all of its volume data can be deleted or has a backup. Inspect the Compose project labels and the volume contents before removing abandoned worktree data.

Treat image cleanup separately from cache and volume cleanup. Inspect image tags and references first. Avoid global `docker image prune -a` while other developers or worktrees use the same engine.

When a worktree is finished, `docker compose -p "$PROJECT" down --rmi local` removes service images without custom tags and stops that project's containers. Verify that `PROJECT` uniquely identifies the worktree before running it. Do not use `--rmi all` for a project that may use shared custom image tags. Removing an image tag may not free layers that another image or the BuildKit cache still uses.

## Research basis

Docker's official guidance recommends project names to isolate feature-branch copies and shared-host stacks. It confirms that `-p` has the highest project-name precedence. The Compose shutdown command keeps named volumes unless you request volume removal. BuildKit garbage collection operates on builder cache, while volume lifecycle is separate.

Community tools such as [worktree-compose](https://github.com/mostafasudo/worktree-compose) and [Docktree](https://docktree.dev/) automate per-worktree project names, port allocation, and state namespaces. Their examples support the same isolation rules. Their automatic cleanup policies are tool-specific, so review them before adopting them for shared development data.

- [Specify a Docker Compose project name](https://docs.docker.com/compose/how-tos/project-name/)
- [Compose build command and image tags](https://docs.docker.com/reference/cli/docker/compose/build/)
- [Compose shutdown behavior](https://docs.docker.com/reference/cli/docker/compose/down/)
- [BuildKit garbage collection](https://docs.docker.com/build/cache/garbage-collection/)
- [Optimize cache usage in builds](https://docs.docker.com/build/cache/optimize/)
- [Docker volume lifecycle](https://docs.docker.com/engine/storage/volumes/)
- [Buildx cache pruning options](https://docs.docker.com/reference/cli/docker/buildx/prune/)
- [Docker Desktop resource limits and file sharing](https://docs.docker.com/desktop/settings-and-maintenance/settings/)
