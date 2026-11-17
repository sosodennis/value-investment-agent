# Measure the complete Fundamental flow

Run `scripts/benchmarks/fundamental_flow.py` against an isolated, configured
Fundamental deployment. The driver times the company/date CLI through
authenticated retrieval of the saved numerical result and provenance. It uses
the deployment's caller and calculator. It supplies no financial inputs or
approval.

Keep the manifest, sources, seeds, outputs and credentials outside Git. A manifest
contains these fields:

```json
{
  "workload": "C",
  "side": "baseline",
  "delivery_sha": "exact Git commit",
  "image": "sha256:exact-image-id",
  "compose_command": ["docker", "compose", "-p", "isolated-project", "-f", "/absolute/compose.yml"],
  "container": "isolated-project-fundamental-service-1",
  "resources": {"cpus": 1, "memory_bytes": 3221225472, "workers": 1},
  "output_directory": "/absolute/benchmark-results",
  "container_output_directory": "/run/benchmark-results",
  "reference_flow": "/absolute/accepted-flow.stdout",
  "seed_manifest": "verified starting-store manifest digest",
  "issuer_arguments": ["fundamental-prepare-issuer", "deployment-specific arguments"],
  "caller_id": "configured-caller",
  "organization_id": "configured-organization",
  "effective_valuation_timestamp": "frozen effective timestamp",
  "driver_timeout_seconds": 930
}
```

Mount `output_directory` at `container_output_directory` so the authenticated
retrieval process can read the exact CLI output. Configure caller credentials
through the existing deployment, rather than adding them to this manifest.

```sh
python3 scripts/benchmarks/fundamental_flow.py \
  --manifest /absolute/manifest.json --label baseline-C-1
```

The driver checks the running image, CPU, memory and worker limits. Each successful
sample must calculate all scenarios, preserve numbers, assumptions and quality
status, and retrieve the saved execution and uncertainty evidence through the
authenticated API. Workload C also requires unchanged applicable signatures and
`wrote=false` for lineage and calculation publications. Restore the declared seed
before each A or B sample. Seed restoration is outside the timed boundary.

The driver retains failed attempts and refuses to overwrite earlier output.
Receipts record wall time, cgroup CPU, sampled cgroup memory, container lifetime
memory peak and host load. Memory values are not process RSS. Post-run equivalence
checks and statistics collection are outside the successful timed boundary.

Profile separate diagnostic runs. Freeze the harness and manifests before the
alternating comparison. One successful run qualifies the driver; it does not
establish a speedup. Verify full table contents, concurrent deduplication,
restarts, restore, refusal and liveness behavior separately.
