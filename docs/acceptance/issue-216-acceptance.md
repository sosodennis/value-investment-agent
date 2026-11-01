# Issue 216 staging acceptance

Verified implementation commit: `e4b2d9efef67f81f810a8cbc54702ea080138763` on
`codex/issue-201-integration`. The run used the dedicated
`value-investment-agent-216-staging` Compose project and the local-only
`.env.staging` file with mode `0600`. The PostgreSQL and Redis volumes were
confirmed disposable for this acceptance and reset before the final run. The
real OpenRouter CSV and `.env.staging` stayed outside Git and are not included
in this document.

## Commands and results

| Check | Result |
| --- | --- |
| `docker compose --env-file .env.staging -p value-investment-agent-216-staging config --quiet` | exit 0 |
| `docker compose --env-file .env.staging -p value-investment-agent-216-staging up -d` | exit 0 |
| `docker compose ... ps` | backend, frontend, provider, model inference, search, PostgreSQL, and Redis healthy; migrations exited 0 |
| `bash -n scripts/organization_staging_acceptance.sh scripts/refactor_staging_smoke.sh` | exit 0 |
| `organization_staging_acceptance.sh` with the real CSV | exit 0; `60/60 VERIFIED` on the exact integration SHA |
| `refactor_staging_smoke.sh` with Bob fixture and `STAGING_BASE_URL=http://127.0.0.1:18580` | exit 0 on the exact integration SHA |
| `refactor_staging_smoke.sh` with Bob fixture, the real CSV, and `STAGING_REQUIRE_LIVE_PROVIDER=1` | exit 0; duplicate import of all 5 existing keys and `key1` through `key5` each returned `healthy`; live workflow completed with the disposable Alpha staging selection `nvidia/nemotron-3.5-super-vl:free` |
| `docker compose ... -f docker-compose.production.yml config --quiet` | exit 0; rendered backend/provider/Search tokens and Search encryption key were all non-empty |
| Browser route acceptance at frontend port `18581` | verified for organization settings, notifications, LLM settings, Search settings, and workspace |
| Secret redaction scan | exit 0; passed against four artifacts, `.env.staging.example`, the real CSV values, and Compose logs |

## Organization acceptance coverage

The fresh staging run registered Alice, Bob, Carol, and Dave; created Alpha
and Beta; and selected organization context explicitly. It verified:

- registered-user directory search and initial membership listing;
- invitation delivery to the recipient's private durable inbox, with no
  cross-recipient visibility;
- accept, duplicate accept, decline, duplicate decline, expiry rejection,
  resend after decline, revoke, and revoked-accept rejection;
- re-invitation, membership acceptance, removal, and access rejection after
  removal;
- ownership transfer, role promotion, and last-owner protection;
- shared LLM settings and provider-key reads for another organization user;
- member denial for provider mutation;
- organization-scoped Search settings and cross-organization denial;
- organization audit read access and cross-organization denial;
- five real CSV keys imported in one batch with `5 imported`, `0 duplicates`,
  `0 failed`, `0 invalid`, and `0 retryable` rows.

The organization report is local evidence at
`/tmp/value-investment-agent-201-e4b2d9-organization.jsonl`; it records only check
names, statuses, HTTP codes, and safe details.

## Runtime and browser evidence

Bob's fixture selected Alpha after login and the runtime smoke verified health,
registration/login, organization context selection, workflow start, ticker
selection, the pending valuation approval boundary, and completion. In the
final state Bob is the transferred owner; the earlier harness assertion also
verified that a regular member cannot mutate provider configuration. The smoke
intentionally did not approve the valuation or execute deterministic
calculation. The CSV smoke imported the five existing keys as duplicates and
tested `key1` through `key5` individually; each returned `healthy`. Failover
is `INCONCLUSIVE` because no primary key fault was injected. The final runtime
report is `/tmp/value-investment-agent-201-e4b2d9-bob-csv-nemotron.jsonl`.

The five-key result does not establish a key-specific OpenRouter 429 threshold.
The observed free Gemma route returned `429` with
`limit_source=upstream_provider_shared_pool`, while `openrouter/free` returned
`404 No endpoints available`. These are upstream model/provider-pool
availability results; individual key health remained successful. The Nemotron
selection was used only for this disposable staging run and is not committed as
an application default.

The frontend was checked at viewport `701x699` in the local in-app browser as
Bob after selecting Alpha on the exact integration SHA:

| Route | Observed result |
| --- | --- |
| `/settings/organization` | Alpha active; member table showed Alice admin, Bob owner, and Dave removed; invitation history visible |
| `/notifications` | private organization invitation inbox showed the accepted invitation |
| `/settings/llm` | Alpha provider page showed import history `5 / 5`, `5 imported`, and masked key suffixes only |
| `/settings/search` | Alpha Search settings showed shared provider availability and organization-scoped provider-key copy |
| `/` and workspace route | analysis input rendered; service capabilities reported Operational |

## Limitations and maintenance

This acceptance proves the local Compose deployment and the organization,
notification, provider-sharing, Search-sharing, and runtime contracts. It does
not certify hosted TLS, reverse-proxy headers/cookies, the optional scheduler,
or failover under injected upstream failure. Re-run this acceptance after any
change to Compose services, environment keys, organization or notification
contracts, provider/Search ownership, invitation lifecycle, route contracts,
or browser navigation and display of these workflows. Update
[`staging-deployment.md`](../runbooks/staging-deployment.md) in the same change
when those procedures or acceptance commands change.
