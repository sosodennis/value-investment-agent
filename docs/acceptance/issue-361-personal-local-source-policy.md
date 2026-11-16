# Personal local source-use configuration

This opt-in deployment catalog records the owner's decision to use Yahoo daily
quotes for personal, noncommercial research on their own machine. It preserves
the existing aggregate and macro source rules. The built-in default catalog
continues to exclude Yahoo quotes.

The catalog permits valuation preparation and local derived valuation display.
It excludes raw-data redistribution, commercial use and services to third
parties. These are declared use limits; the catalog does not configure network
bindings or authenticate users.

## Enable the configuration

Build an image containing this commit. Append
`compose/verification/docker-compose.personal-local-sources.json` to the
deployment's existing Compose file list. The overlay selects the packaged
catalog through the existing `FUNDAMENTAL_SOURCE_USE_POLICY_FILE` and
`FUNDAMENTAL_SOURCE_USE_POLICY_DIGEST` settings. It adds no ports, volumes,
credentials or services. Apply the same settings to standalone issuer/source
commands and the release canary.

The catalog is packaged at
`/app/src/fundamental_service/resources/personal-local-source-use-v1.json`.
Its version is `personal-noncommercial-local-source-use-v1`; its canonical digest
is `a7ff57184cd22632a91a119dee78e414b6db5a12e3b941df190efa82cb4bb6ea`.
Update both the market-source and quote-source policy pins in generated source
plan configurations to that version and digest. Existing plans, admissions,
releases and caller approvals retain their old identities; regenerate downstream
inputs instead of reusing their approval.

Yahoo terms are checked against the complete `section#node-content` element,
including its restrictions. The pinned element digest is
`f6ff1ebb920c22b867fe4f126218677682d06958be30f5f1bbb6db1eceddca2b`.
Retain the original terms outside Git. Missing or changed terms still refuse
admission. Removing the overlay restores the built-in catalog; plans must then
use the corresponding original policy pins.

## Evidence limits

This is an operator-use decision, not permission from Yahoo or its data
providers. No separate provider authorization for automated collection has been
supplied or verified. The policy retains this fact in its `basis` and notices;
matching the catalog cannot establish external source rights or satisfy #361's
provider-rights acceptance. It is also not a trusted release or caller approval.

Focused tests exercise the real runtime loader with the overlay's digest,
preserve the default refusal, and stop an opted-in capture at an intercepted
transport boundary. They make no network request and establish no real quote,
numerical valuation or deployment acceptance. The active #361 runtime is not
changed by adding these files to the branch.

## Increment validation

The focused policy, deployment, Yahoo preparation/reproduction and source
admission suite passed 110 tests, with no skips:

```sh
cd fundamental-service
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_personal_local_source_policy.py tests/test_source_use_deployment.py \
  tests/test_yahoo_quote_preparation.py tests/test_yahoo_quote_source.py \
  tests/test_source_admission.py -q
```

Ruff 0.14.10 lint/format, both architecture guards and `git diff --check` pass.
The active runtime's recorded Compose file set plus the new overlay passes
`docker compose ... config --quiet`; no container is started or replaced.
This increment changes no production Python signatures or public wire schemas.
Whole-PR review, CI, deployment and real quote/numerical acceptance remain
separate checks; none is inferred from the local tests.
