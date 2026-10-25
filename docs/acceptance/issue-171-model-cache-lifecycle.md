# Issue 171 model cache lifecycle verification

Verification run on 2026-10-26 in isolated Compose project `value-investment-agent-i171-cache` from branch `codex/issue-171-model-cache-lifecycle`.

## Storage evidence

The issue's recorded baseline found the active stack stored the model snapshots both in image layers and in writable volumes: 837 MiB for news sentiment, 420 MiB for SEC FLS, and 976 MiB for the backend embedding cache. The baseline also identified retired project cache volumes retaining about 2.34 GB each. Those existing projects and volumes were left untouched.

For this verification project, the built inference images measured 1,730,581,887 bytes (news) and 1,292,903,868 bytes (FLS). Inside the containers, `/opt/hf-cache-baked` measured 837 MiB and 420 MiB respectively. `docker inspect` reported no mounts for either inference service; `docker volume ls` returned no model cache volume for the project. Thus the snapshots reside in each service image only, with no second runtime copy. The backend image measured 3,057,529,511 bytes; its baked cache measured 976 MiB and `docker inspect` reported no mounts.

The existing runtime-cache override remains an explicit exception: it seeds project-scoped writable volumes from baked artifacts. Those volumes are disposable cache state and can be removed after the project's containers are stopped with `scripts/docker/retire-worktree-model-caches.sh <project>`.

## Commands and results

Compose validation passed with the dedicated ports: backend 8510, Postgres 8533, Redis 8481, provider 8512, and search 8513. The config command emitted only the expected warning that `FRED_API_KEY` was unset.

Cold launch:

```sh
LITELLM_MASTER_KEY=local-validation-only \
INFERENCE_SERVICE_TOKEN=offline-validation-token \
MODEL_INFERENCE_TOKEN=offline-validation-token \
BACKEND_HOST_PORT=8510 POSTGRES_HOST_PORT=8533 REDIS_HOST_PORT=8481 \
LLM_PROVIDER_SERVICE_HOST_PORT=8512 SEARCH_SERVICE_HOST_PORT=8513 \
docker compose -p value-investment-agent-i171-cache up -d --build \
  postgres redis llm-provider-service model-inference-news \
  model-inference-fls search-service backend
```

The first launch attempt omitted the required inference service token and the two model containers exited. Supplying a local verification token recreated them successfully; no production credential was used. Postgres, Redis, provider, backend, and both inference services became healthy. Search remained unhealthy with `/readyz` returning 503 because its control plane did not report ready in this isolated configuration. Backend `/health` returned `{"status":"ok"}`.

Both model services reported `ready: true` for their pinned revisions. Real offline inference succeeded for `news.sentiment` and `sec.fls`; the outputs included a positive sentiment score and an FLS prediction. The inference containers had `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_LOCAL_FILES_ONLY=1` from Compose.

Restart verification used `docker compose -p value-investment-agent-i171-cache restart model-inference-news model-inference-fls`. Both returned to healthy and again reported their pinned revisions. FLS inference succeeded after restart. The first sentiment request exceeded the existing 500 ms default operation deadline (observed runtime 641 ms); retrying with the supported `deadline_ms: 1000` succeeded. No model download or volume seeding occurred during restart.

The retirement helper was exercised against four synthetic volumes labelled for a separate test project: three recognized model cache volumes and one `pg_data`. It removed only the three cache volumes, preserved `pg_data`, and a second invocation reported zero removals. No active project or real database volume was passed to the helper.

## Remaining verification limits

The search service's unrelated readiness failure remains outside this cache lifecycle change and should be investigated before claiming the entire development stack is healthy. The default model path and both model services passed cold-load, restart, offline inference, and no-volume checks. Existing cache volumes in other projects remain untouched by design.
