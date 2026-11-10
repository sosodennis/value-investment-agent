# Docker storage without interrupting development

Use separate Compose projects, ports, networks and database volumes for each
worktree. Reuse immutable image layers and build cache across those projects.
Storage work must not replace another worktree's images or restart its services.

## Inspect before acting

Run `docker system df`, then inspect the relevant images, container references,
volume labels/contents and selected builder. Image sizes include shared layers;
BuildKit can retain layers after image deletion. Do not add the image and cache
figures or sum every image's displayed size to estimate reclaimed disk space.
Compare free space inside the Docker VM before/after a cleanup as well.

Record container IDs, image IDs and start times before candidate validation.
Use new candidate image tags and an isolated Compose project. Build and test
one large service at a time, with CPU/memory limits on disposable verification
containers. Verify existing container IDs and start times afterwards. Cleanup
only the candidate project's resources.

## Keep runtime images small

The backend and Fundamental Dockerfiles separate dependency installation from
source copying. Compiler tools and uv download caches stay in build stages;
only the installed environment, application and required runtime libraries
reach the runtime image. `COPY --chown` assigns Fundamental ownership without
a later recursive chown layer copying its installed environment again.

Use the pinned Python base digests and uv versions in each Dockerfile. Update
pins deliberately with runtime checks; a common base can improve layer reuse
but does not guarantee identical package-install layers. Distribution package
repositories are not snapshot-pinned, so do not claim bit-for-bit reproducible
images solely from a pinned base and uv.lock.

uv uses a BuildKit cache mount with `UV_LINK_MODE=copy`. This keeps downloads
reusable without baking a second download cache into the runtime image. Keep
source files after dependency/model stages so a source-only rebuild does not
reinstall dependencies or download weights. Preserve the existing `uv` command,
virtualenv paths, entrypoints and source mount locations for development.

### Compile extensions during development

The normal backend runtime omits compilers. When an in-container task needs
`gcc`, `g++` or PostgreSQL headers, select the explicit development target:

```sh
docker compose -p "$PROJECT" \
  -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.build-tools.yml config --quiet
docker compose -p "$PROJECT" \
  -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.build-tools.yml build backend backend-migrations
```

Use that same ordered file list for the project's subsequent commands. Keep
`PROJECT` unique and retain that worktree's env-file and host ports. The overlay
also selects the development target for optional backend schedulers. Existing
running projects are changed only when their own operator explicitly recreates
them using the new images.

## Bake the files the existing loaders use

`finance-agent-core/scripts/bake_models.py` pins both embedding snapshots and
lists the required files: SentenceTransformer safetensors plus tokenizer/pooling
metadata, and FastEmbed's ONNX model plus tokenizer metadata. Its offline
`refs/main` files point to those immutable revisions because the existing
backend loaders request the default ref.

`model-inference-service/scripts/bake_models.py` keeps root tokenizer/config
files and one supported PyTorch weight set at the configured revision. It
prefers safetensors, supports sharded weights and their index, and falls back
to `pytorch_model*.bin` for the FLS snapshot. Alternate TensorFlow, OpenVINO,
ONNX and training weights do not belong in these classifier images. A custom
model repository must use the supported root-level Hugging Face layout.

Keep both PyTorch and ONNX runtime dependencies: the backend currently has a
SentenceTransformer loader and a separate FastEmbed loader. Removing PyTorch
or switching engines/quantization changes behavior and needs its own evaluation.
Continue using immutable baked artifacts for normal offline startup. A shared
writable model volume across worktrees would weaken ownership and reproducibility.
See [model artifact ownership](model-artifact-cache.md) for the explicit writable
cache exception.

## Validate a storage change

1. Record the source commit, Dockerfile/lockfile/model pins, candidate image IDs,
   ordered Compose files, project identity and command results.
2. Start candidate model services with the Hugging Face offline flags on an
   internal-only network. Verify readiness, loaded revisions and real News/FLS
   inference. Verify SentenceTransformer and FastEmbed embeddings offline too.
3. Compare fixed inputs against the original runtime's outputs. Preserve model
   revisions, labels, rankings and numerical tolerances; a smaller image with
   unavailable models or degraded retrieval is a failure.
4. Verify runtime shared-library dependencies and any compiler-enabled development
   target. Test Fundamental's own readiness and data path under its non-root user.
5. Rebuild with unchanged inputs and after a source-only edit in a disposable
   build context. Check that dependency and model steps are cached. Restore the
   context and do not edit a worktree that another task is using.
6. Compare image sizes, model file inventories, build-cache usage and Docker VM
   free space separately. Preserve the previous exact image for rollback until
   acceptance succeeds, then retire only owned candidate resources.

## Retain useful cache and retire owned resources

Build cache is shared by the selected builder. First run `docker buildx ls` and
`docker buildx du --verbose`. The Docker Desktop default GC target is 20 GB;
inspect the installed builder's policies instead of assuming automatic GC is
disabled because a large cache remains. A reclaimable cache is reusable build
work, not an unused database or a promise that all bytes can be released at once.

Prefer age/size-bounded cleanup of unused cache during an idle period. For
example, after reviewing the matching records, `docker buildx prune --filter
"until=168h" --max-used-space 20gb` targets old cache on the selected builder.
Record that pruning may slow later builds. Do not modify/restart Docker Desktop
or its daemon configuration as a shortcut during another task's acceptance run.

Only retire a Compose project after its issue/release evidence and owner agree
it is no longer needed. A container's age or a closed issue alone is not evidence
that its database can be discarded. Check stopped containers too. Keep database
volumes unless they are confirmed disposable or have a verified, checksummed
backup outside the Docker VM. An archive on the host frees VM capacity but still
uses host disk; retain its ownership metadata and restore instructions.

For dangling images belonging to one exact project, the cleanup helper requires
an explicit project and retains its existing age window:

```sh
DOCKER_CLEANUP_PROJECT="$PROJECT" \
DOCKER_DANGLING_IMAGE_RETENTION_HOURS=168 \
  scripts/cleanup-docker-images.sh
```

The helper does not remove tagged/referenced images, volumes or BuildKit cache.
Inspect and remove other explicitly selected unused tags individually. Follow
[worktree retirement](../issue-worktree-lifecycle.md#retire-branches-worktrees-and-compose-resources)
and the [model cache retirement runbook](model-artifact-cache.md#retire-a-worktree).
Never run global image/volume/system pruning for worktree cleanup.

## References

- [Docker multi-stage builds](https://docs.docker.com/build/building/multi-stage/)
- [Docker build-cache optimization](https://docs.docker.com/build/cache/optimize/)
- [Docker BuildKit garbage collection](https://docs.docker.com/build/cache/garbage-collection/)
- [Docker buildx prune filters](https://docs.docker.com/reference/cli/docker/buildx/prune/)
- [uv in Docker](https://docs.astral.sh/uv/guides/integration/docker/)
- [Hugging Face download filtering and revisions](https://huggingface.co/docs/huggingface_hub/guides/download)
