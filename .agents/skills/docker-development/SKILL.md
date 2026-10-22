---
name: docker-development
description: Use this project guidance when configuring or running Docker Compose for local development, tests, or concurrent worktrees. Covers stack isolation, ports, state, builds, cache, and cleanup. Not for production deployment.
---

# Docker development

Use this skill before changing Compose configuration, starting or building a stack, running containerized tests, or cleaning Docker resources for this project.

## Inspect the current stack

- Read the root `docker-compose.yml` and any Compose override files used by the task. The service and profile list can change, so derive it from the current files instead of relying on a remembered list.
- Run `docker compose config --quiet` to validate Compose configuration. Use `docker compose config --services` and `docker compose config --profiles` to inspect the current services and profiles.
- Start only the services and profiles needed for the task. Optional services still consume shared host resources when they run.
- The project currently uses profiles, environment-backed host ports, and Compose-managed named volumes. Keep those patterns when adding services.
- Keep `.env` and other developer-specific port overrides untracked. The root `.gitignore` already ignores `.env`.
- Do not print or paste resolved Compose configuration when it contains secrets. Use `config --quiet` for validation.
- Bind-mount source files only when the development workflow needs live host edits. Keep database files and large caches in Docker-managed volumes because Docker Desktop file sharing adds overhead.

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
