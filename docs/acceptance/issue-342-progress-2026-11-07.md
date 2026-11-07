# Issue 342 progress checkpoint

This record is a work-in-progress checkpoint. It is not an acceptance or
VERIFIED record.

## Code checkpoint

- Issue: #342, blocker for #325
- Branch: `codex/issue-342-fact-selector`
- Commit: `1ff0c3e5` (`fix(#342): prefer consolidated facts during snapshot resolution`)
- Pull request: pending

The canonical snapshot resolver now narrows each required normalized field to
eligible, dimensionless facts whose XBRL context has
`consolidation_scope=consolidated`. It retains dimensional candidates in the
selection provenance, chooses the latest period and longest duration for a
shared period end, and still fails closed with `FACT_CONFLICT` when eligible
consolidated totals disagree.

## Automated checks

All commands exited 0 at the code checkpoint unless noted otherwise:

- `cd fundamental-service && uv run pytest tests/test_facts.py -q`: 13 passed.
- `cd fundamental-service && uv run pytest tests/test_sec_rebuild.py tests/test_api.py -q`: 47 passed.
- `cd fundamental-service && uv run pytest -q`: 229 passed, 25 skipped, and one existing Pydantic serializer warning.
- `python3 scripts/architecture_guard.py`: passed with no boundary violations.
- `cd fundamental-service && python -m compileall -q src tests/test_facts.py`: passed.
- `git diff --check`: passed.
- Commit hooks: Ruff, Ruff format, trailing whitespace, end-of-file, YAML, and large-file checks passed.

`uvx ruff check` reports pre-existing baseline findings in the touched module
and test file (quoted annotations, import ordering, UTC style, and unrelated
test literal style); the repository commit hooks use the pinned Ruff checks,
which passed for the committed files.

## Live Compose checkpoint

- Compose project: `value-investment-agent-341-msft-identity`
- Fundamental service host port: `18796`
- PostgreSQL host port: `18797`
- PostgreSQL volume retained: `value-investment-agent-341-msft-identity_fundamental-postgres-data`
- Service data volume retained: `value-investment-agent-341-msft-identity_fundamental-service-data`
- Rebuilt service image: `sha256:b2ec12d0dbceb40a7ac6d79ae42f65755d5fb1121704cab9032c3b3b3b42058b`
- `GET http://127.0.0.1:18796/readyz`: HTTP 200,
  `{"status":"ready","contract_version":"internal.v1"}`
- PostgreSQL and Fundamental service containers: healthy

The service was rebuilt from commit `1ff0c3e5` with the existing database and
service data volumes. No volume deletion or global Docker cleanup was used.

## Signed snapshot resolution

The existing persisted MSFT release was used without synthetic facts or a
local fallback:

- Identity: CIK `0000789019`, `MICROSOFT CORP`, US-GAAP/USD, ticker `MSFT`.
- Snapshot: `snapshot-23146d7e2b74d2d512cbc714181c1192`.
- Active release profile: `sec-public-pit-msft-issue341`, revision `1`.
- Release manifest digest: `846c625f1d051260a6016e4f948911edc5710d4bde05388df0c4c610c48edd15`.
- Signed request: `POST /v1/data/snapshots/resolve` with correlation ID
  `issue-342-live-msft-snapshot-resolve`, required field `revenue`, and
  `source_selection_policy=pit-v1`.
- Response: HTTP 200, `quality=verified`, no issue codes, and one selected
  historical fact `sec-fact-fc44c34fd48d515dd34e5267`.

The previous HTTP 422 `FACT_CONFLICT` caused by the 57-fact normalized-field
collision is resolved at the service-owned selector boundary. This checkpoint
does not close #342 or mark #325 verified; PR review, merge to `main`, and the
combined #325 UI acceptance remain pending.
