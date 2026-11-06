# Issue #330 SEC Filing Resource Resolution

Issue: https://github.com/sosodennis/value-investment-agent/issues/330; PR: #331 (targets `main`); branch: `codex/issue-330-sec-resource-resolution`; verified code commit: `21ca2abe5304ed5ca40b7d1f77ed7ebfd57e410b`.

## Finding and Behavior

The AAPL direct-parser A/B test distinguishes two inputs. With the two local
images absent, Arelle reports two blocking
`EFM.5.02.05.graphicFileError` findings. With the images read from the
accession-matched SEC ZIP, those findings disappear. Both runs retain
`EFM.5.02.05.disallowedElement` for the trailing script in the direct HTTP
representation, and their fact counts and semantic digests match. Network
attempts are blocked and remain zero.

The service ingestion path first verifies and normalizes the direct response
against the accession index and canonical archive member. The normalized AAPL
HTML references the two archive images; the service stages those bytes beside
both parser inputs. The exact-head integration test now verifies the expected
successful publication, verified fact, retained raw response, equal normalized
and archive fact digests, zero network attempts, and stable replay manifest.
This replaces an older assertion that expected the missing-image rejection
even after image staging was added.

| Fixture artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| AAPL direct-response HTML | 1,503,779 | `a14d584e9804a87e92ddbd2446ade975e926a494671292403c811c1f4fc4b846` |
| Accession-matched XBRL ZIP | 458,550 | `c19944b22ee101abbfd69b2e6fa4f30e0ec511ad276fdbb3cf3ef5dce3938fee` |
| `aapl-20240928_g1.jpg` | 10,963 | `d34f70bca1c0667ed6e35acdfc5cce311ae1788650986c40d72a3eda2df5535d` |
| `aapl-20240928_g2.jpg` | 154,498 | `ddf66142bad17b22f2500aa31a45ce0bcdf69ae69a2535878868005b0a0675f0` |

The recorded direct EFM A/B measurement is 1,127 facts and digest
`c517db6b978576b9191cbe79267bf7737d71219a106cffbb9caef4795c5b945c` in both
runs. The exact-head test reran this comparison and passed its equality,
finding-severity, and zero-network assertions.

## Verification on `21ca2abe`

| Check | Result |
| --- | --- |
| Focused SEC integrity, ingestion, and Arelle parser suite with `ISSUE328_*` runtime | exit 0; 31 passed, 2 skipped |
| Pinned AAPL and Microsoft SEC EFM/DQC replay with `ISSUE312_*` runtime | exit 0; 2 passed |
| `python3 -m compileall -q fundamental-service/src fundamental-service/tests` | exit 0 |
| Ruff format check and lint for `test_ingestion.py` | exit 0 |
| `git diff --check` | exit 0 |
| Commit hooks | exit 0; whitespace, EOF, large-file, Ruff, and Ruff-format checks passed |
| Compose config validation | exit 0 |
| Compose build and startup | exit 0 |
| PostgreSQL / Fundamental service health | both `healthy` |
| `GET /livez` | exit 0; `{"contract_version":"internal.v1","status":"ok"}` |
| `GET /readyz` | exit 0; `{"status":"ready","contract_version":"internal.v1"}` |
| Fundamental service image | `sha256:730093852b903c5d0495f55a96f43337db3b1fbf926e1605c7b75c8b9b0d51e6` |

The first focused suite invocation skipped two tests because it supplied only
`ISSUE328_*` variables. Those are the pinned AAPL and Microsoft EFM/DQC replay
tests; both were run separately with `ISSUE312_*` variables and passed.
Therefore no Arelle, EFM, DQC, or Xule error was reproduced in these acceptance
tests. This does not claim to resolve the separate plugin/hooks investigation
tracked by #333.

Commands on the verified code commit:

```sh
FUNDAMENTAL_TEST_DATABASE_URL=postgresql+asyncpg://fundamental:fundamental@127.0.0.1:18093/fundamental \
ISSUE328_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
ISSUE328_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
ISSUE328_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
ISSUE328_TAXONOMY_CACHE_DIR=/tmp/issue312-sec-taxonomy-2023-2024 \
uv run --extra dev --project fundamental-service pytest -q -rs \
  fundamental-service/tests/test_sec_integrity.py \
  fundamental-service/tests/test_ingestion.py \
  fundamental-service/tests/test_arelle_parser.py

ISSUE312_EDGAR_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/EDGAR-4891c4c9889c77af247428ceff4fa7cc52d534ea \
ISSUE312_XULE_PLUGIN_DIR=/private/tmp/issue312-validation-runtime-v2/xule-7ca1d7637f333f5c3a02379dbe6f6d6c17c88acc/plugin \
ISSUE312_DQC_RULESET_PATH=/private/tmp/issue312-validation-runtime-v2/dqc_us_rules-31.0.3/dqc_us_rules/dqc-us-2024-V31-ruleset.zip \
ISSUE312_TAXONOMY_CACHE_DIR=/tmp/issue312-sec-taxonomy-2023-2024 \
uv run --extra dev --project fundamental-service pytest -q \
  fundamental-service/tests/test_arelle_parser.py::test_apple_sec_efm_dqc_replay_with_pinned_runtime \
  fundamental-service/tests/test_arelle_parser.py::test_microsoft_sec_efm_dqc_replay_uses_canonical_sec_archive_bytes

python3 -m compileall -q fundamental-service/src fundamental-service/tests
uvx --from ruff ruff format --check fundamental-service/tests/test_ingestion.py
uvx --from ruff ruff check --select E,F,I --ignore E501 fundamental-service/tests/test_ingestion.py
git diff --check

FUNDAMENTAL_POSTGRES_HOST_PORT=18093 FUNDAMENTAL_SERVICE_HOST_PORT=18633 \
docker compose -p value-investment-agent-330-sec-resource-resolution \
  -f compose/verification/docker-compose.issue280-operations.yml config --quiet
FUNDAMENTAL_POSTGRES_HOST_PORT=18093 FUNDAMENTAL_SERVICE_HOST_PORT=18633 \
docker compose -p value-investment-agent-330-sec-resource-resolution \
  -f compose/verification/docker-compose.issue280-operations.yml up -d --build \
  fundamental-postgres fundamental-service
docker compose -p value-investment-agent-330-sec-resource-resolution \
  -f compose/verification/docker-compose.issue280-operations.yml ps
curl -fsS http://127.0.0.1:18633/livez
curl -fsS http://127.0.0.1:18633/readyz
```

PR #331 targets `main` and currently points at exact head
`2eb07e9fe65d7ae27a31d8813a7aa06bb4d774ff`. GitHub run
`42262688272` completed on that SHA: all 11 applicable checks passed and
`fundamental-release-gate` was skipped. The PR is `MERGEABLE` with a `CLEAN`
merge state. Merge and issue closure remain pending until the current
docs-only checkpoint's CI also completes.
