# Issue #373 Docker storage acceptance

Local acceptance: **PASS**. PR review, GitHub CI and merge verification remain
separate gates. Existing development stacks have not been rolled out to these
images. This is storage/runtime acceptance, not SEC ingestion or valuation
acceptance for #361.

## Source and runtime

- Issue: <https://github.com/sosodennis/value-investment-agent/issues/373>
- Branch: `codex/issue-373-docker-storage`; base `485b2f59742454151faf56730e1e421e850cf978`.
- Tested implementation: `3490bd8c13ccd3c90e1f3f4b9b40561ce5ed7590`.
- Later documentation-only checkpoint: `4a02cd253993c2972722c40d00e7076eee59595c`.
- Worktree: `/Users/denniswong/.codex/worktrees/issue-373-docker-storage/value-investment-agent`.
- Compose project: `value-investment-agent-373-storage-verify`.
- Ordered Compose input: `compose/verification/docker-compose.issue373-storage.yml`;
  no env file, no published ports, internal-only network, two disposable named
  volumes. News and FLS were started sequentially with CPU/memory limits.
- Standalone model probes: `--network none --cpus 1 --memory 2g`, exact image
  IDs, all Hugging Face offline flags enabled. No browser was required.

Python 3.11 builds used the documented `PYTHON_IMAGE` override to a task-owned
local tag containing the **same verified official pinned bytes**. The builder's
Docker Hub metadata lookup stalled; a host registry download verified the index,
arm64 manifest, blobs and layer diff IDs before loading a Docker archive. No
Docker Desktop configuration was changed. Python 3.12 used its normal pinned
default. The evidence records the exact pins, import receipt and build commands.

## Measured images and model artifacts

Sizes below are logical image bytes, including shared layers. They are not a
claim of immediately reclaimed Docker VM space. Baselines are the retained test
stack images, plus the retained `325-327-acceptance` Fundamental image.

| Image | Baseline bytes | Candidate bytes | Reduction |
| --- | ---: | ---: | ---: |
| Backend | 3,105,646,234 | 1,849,593,244 | 40.4% |
| News inference | 1,730,854,011 | 1,276,060,578 | 26.3% |
| FLS inference | 1,293,176,814 | 1,276,481,404 | 1.3% |
| Fundamental | 562,592,002 | 367,219,596 | 34.7% |

| Model files | Baseline bytes / files | Candidate bytes / files |
| --- | ---: | ---: |
| Both embedding engines | 1,068,284,724 / 38 | 182,901,457 / 16 |
| News classifier | 876,926,575 / 9 | 438,907,631 / 6 |
| FLS classifier | 439,335,911 / 6 | 439,331,105 / 3 |

All retained model files match baseline SHA-256 values. Both embedding engines
and News/FLS produced **exactly equal** outputs on the probe's three fixed
inputs (maximum absolute difference `0`; allowed tolerance `1e-6`). Labels,
rankings and revisions matched. This is a representative behavior regression
check, not an accuracy evaluation. No model engine or quantization changed.

All third-party Python package versions and Python versions match baseline.
The baseline backend also contained source-tree `finance-agent-core` egg-info
metadata, which is absent in this fresh checkout; it is not an omitted third-party
dependency. The candidate backend composition root imports successfully.

## Checks and command results

All commands below exited `0`; exact image IDs, complete probe/build commands,
package/file inventories, fixed outputs and execution helpers are in the evidence
bundle. Host `ruff` and Python executables came from existing environments used
read-only; no dependencies were installed into another worktree.

- Model service suite: `PYTHONDONTWRITEBYTECODE=1 <existing-service-python> -m pytest -p no:cacheprovider tests -q`:
  **25 passed**. Includes safetensors preference, FLS binary fallback, sharded
  weights/index retention and missing-weight rejection.
- Ruff check/format: four changed Python files and the full inference `src tests`.
- `PYTHONDONTWRITEBYTECODE=1 python3 scripts/architecture_guard.py`: no violations.
- `bash -n scripts/cleanup-docker-images.sh`; four fake-Docker scope/failure
  checks. Missing/invalid projects and invalid retention fail before Docker;
  valid input includes exact project, dangling and age filters. No real prune ran.
- Isolated Compose `config --quiet`, `up -d --wait`, readiness and authenticated
  News/FLS inference. Service outputs exactly equal baseline; missing credentials
  return `401`. Fundamental is ready and UID `10001` can write/read/delete its
  own data-path probe. SEC identity resolution is intentionally unconfigured here.
- Native runtime imports: Torch, SciPy, NumPy, pandas, scikit-learn, psycopg,
  FastEmbed and spaCy `en_core_web_sm` 3.8.0; `libpq`, `libgomp`, `libstdc++` load.
- Opt-in backend development target: `gcc`, `g++`, PostgreSQL headers,
  `uv 0.13.6` and `supercronic v0.2.38` available. Compose configuration with
  `--profile '*'` selects the development target for backend, migrations and
  optional schedulers; backend/migrations retain their shared image identity.
- All four unchanged-input builds reused their exact original image digest.
  A source-only edit in a disposable `git archive` context changed the final
  digest while **all dependency/model steps remained cached**. No live worktree
  source was edited for the cache experiment.
- `git diff origin/main --check`: pass; checkpoint hooks passed.

## Isolation, cleanup and limits

The baseline had 62 containers, 37 running. Sixty retained their exact IDs,
image IDs, running state and start time. Two #361 service containers were
recreated concurrently by the main chat; its work was inspected read-only.
Both replacements reported ready with SEC identity resolution configured. This
task did not operate either #361 project or modify its files/checkpoints.

Only #373's four verification containers, internal network, two disposable
volumes and ten temporary candidate/source-check/development/base image tags
were removed. Old images remain for their existing stacks. Shared BuildKit
cache was retained; no global prune or daemon restart/configuration change ran.
The post-cleanup engine still has 37 referenced volumes, about 2.27 GB.

Local execution covered arm64 Docker Desktop. AMD64 builds were not executed.
OS package repositories are not snapshot-pinned, so clean-build bit-for-bit
reproducibility is not claimed. Cached repeat builds were verified. Current
development images change only through an owner-controlled per-project rollout;
rollback instructions are in the updated storage runbook.

## Evidence identity

The [compressed evidence](issue-373-storage-evidence.json.gz) contains canonical
JSON, input file digests and command results. Decode with Python's standard
`gzip` and `json` modules. Local raw logs remain in `/tmp/issue373-evidence`.

- Input digest: `8b2b6261761a290f15ffefcbd0b1ad839d40902887f11eefd19dd3812fe0a8d9`.
- Uncompressed output SHA-256: `2be6a1808699eb1ced756cbfa7ea0f3fbc27cbe431ffdf2f11581439c4f611f6`.
- Gzip file SHA-256: `67ebc9e3310274915529689aa504528fb4e5f9f6d26983185e4ad7e159fb8743`.

Checkpoints: `4aeb1c0a` implements the image/model changes; `3490bd8c` adds the
offline probe and isolated service configuration; `4a02cd25` documents safe
rollout/rollback. All remain issue-scoped. Next: PR review and CI, followed by
merge-commit verification and branch/worktree retirement if merged.
