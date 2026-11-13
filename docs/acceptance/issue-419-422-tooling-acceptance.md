# Issues 419 and 422: independent tooling delivery

Base: `52e84dfe5a0dae0c11d2e62fd9a58e885b6eadc9` (`main`).
Verified implementation: `b289b798461535506a9fadbeebaa8d61724c64fb`.
Branch: `codex/issue-419-422-tooling-main`.
Worktree: `/Users/denniswong/.codex/worktrees/issue-419-422-tooling-main/value-investment-agent`.

The service guard previously decoded vendor files under `.venv` and checked only
the first alias of an import statement. It now checks the owned `src`, `tests`
and `scripts` roots, every import alias, and the existing Docker/authentication
markers. This ports the existing fix from `0b294393` onto main.

The Agent hooks retain Ruff 0.3.0; Fundamental-only hooks use its existing CI pin,
Ruff 0.14.10. Their path predicates are disjoint. Only the hook configuration is
taken from `2b3b3927`; provider modules and documentation remain in #370.

Ownership: two existing tooling modules/configurations, with no public service
contract or topology change. The guard reads owned source and Dockerfile bytes;
the commit hooks check the selected tracked paths. No provider, valuation,
database, trust, application workflow or Compose change is included. This bounded
delivery can complete these two tooling issues while #361 remains unfinished.

## Exact implementation checks

Runtime: frozen `fundamental-service/uv.lock`, Python 3.11.15, Ruff 0.14.10,
mypy 1.19.1 and pre-commit 4.3.0. The worktree was clean throughout these checks.

| Command | Exit / result |
| --- | --- |
| `uv run --frozen --extra dev --project fundamental-service pytest -q fundamental-service/tests` | 0; 316 passed, 25 skipped, one existing Pydantic serializer warning |
| `uvx --from ruff==0.14.10 ruff check fundamental-service/src/fundamental_service/architecture_guard.py fundamental-service/tests/test_architecture_guard.py` | 0 |
| `uvx --from ruff==0.14.10 ruff format --check fundamental-service/src/fundamental_service/architecture_guard.py fundamental-service/tests/test_architecture_guard.py` | 0; both formatted |
| `uvx --from mypy==1.19.1 mypy --python-executable fundamental-service/.venv/bin/python fundamental-service/src/fundamental_service/architecture_guard.py` | 0; checked one changed production module with real installed service dependencies |
| `python3 scripts/architecture_guard.py` | 0; no boundary violations |
| `uv run --frozen --project fundamental-service python -m fundamental_service.architecture_guard` | 0 |
| `uvx --from pre-commit==4.3.0 pre-commit validate-config finance-agent-core/.pre-commit-config.yaml` | 0 |
| `uvx --from pre-commit==4.3.0 pre-commit run --config finance-agent-core/.pre-commit-config.yaml --files fundamental-service/src/fundamental_service/architecture_guard.py fundamental-service/tests/test_architecture_guard.py finance-agent-core/api/__init__.py` | 0; both old Agent hooks and new Fundamental hooks passed |
| `git diff --check` | 0 |

The twelve guard cases include a cp1252 third-party module, forbidden imports in
every owned root, an import hidden as the second alias, and retained legacy-marker
and Docker checks. The full suite includes these cases. The actual commit hooks
also passed during commit creation, without bypassing a hook.

Retained failed attempt: standalone `uvx ... mypy <guard.py>` exited 1 because its
environment lacked Pydantic and followed package imports. The dependency-aware
command above passes. This is not a relaxed missing-import or type-ignore result.

External command receipt, including the failed attempt and complete outputs:
`/Users/denniswong/Desktop/Project/value-investment-agent-issue-376-research-evidence/issue-419-422-tooling/87cf3e677ab31a729c926f776f77e607f6bc0d9c8d641945633a33735c87be98.checks.json`.

- Input digest: `023f0785a5f10567a80a803c303d776624f9cb7d951614277495b442527dbede`.
- Output digest: `0c55aac0c9fce5b72193d1a259e2cfd75345904f0e8228908e50cbd5078951e5`.
- Receipt content digest: `87cf3e677ab31a729c926f776f77e607f6bc0d9c8d641945633a33735c87be98`.

No Docker/live-service/UI acceptance is required or claimed for this tooling-only
diff. Database and configured SEC fixture tests skipped locally remain explicit;
CI runs its normal PostgreSQL-backed gate. Independent review, exact-head CI,
main merge and merge-commit revalidation remain pending at this checkpoint.
Raw historical inputs and generated evidence remain outside Git.
