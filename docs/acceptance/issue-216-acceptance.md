# Issue 216 staging acceptance

Verified implementation commit: `4457aabe38d859dafa35eeb3140a14d79483dcc0` on
`codex/issue-216-staging-acceptance`. The run used the dedicated
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
| `organization_staging_acceptance.sh` with the real CSV | exit 0; `60/60 VERIFIED` |
| `refactor_staging_smoke.sh` with Bob fixture and `STAGING_BASE_URL=http://127.0.0.1:18580` | exit 0 |
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
- shared LLM settings and provider-key reads for an organization member;
- member denial for provider mutation;
- organization-scoped Search settings and cross-organization denial;
- organization audit read access and cross-organization denial;
- five real CSV keys imported in one batch with `5 imported`, `0 duplicates`,
  `0 failed`, `0 invalid`, and `0 retryable` rows.

The organization report is local evidence at
`/tmp/value-investment-agent-216-organization.jsonl`; it records only check
names, statuses, HTTP codes, and safe details.

## Runtime and browser evidence

Bob's fixture selected Alpha after login and the runtime smoke verified health,
registration/login, organization context selection, workflow start, ticker
selection, the pending valuation approval boundary, and completion. The smoke
intentionally did not approve the valuation or execute deterministic
calculation. Its provider-key checks were `INCONCLUSIVE` because the fixture
does not contain raw provider keys; the preceding organization run verified the
five live key imports and tests. Failover is `INCONCLUSIVE` because no primary
key fault was injected.

The frontend was checked at viewport `701x699` in the local in-app browser as
Bob after selecting Alpha:

| Route | Observed result |
| --- | --- |
| `/settings/organization` | Alpha active; member table showed Alice admin, Bob owner, and Dave removed; invitation history visible |
| `/notifications` | private organization invitation inbox showed the accepted invitation |
| `/settings/llm` | Alpha provider page showed import history `5 / 5`, `5 imported`, and masked key suffixes only |
| `/settings/search` | Alpha Search settings showed shared provider availability and organization-scoped provider-key copy |
| `/` and workspace route | analysis input and recent runtime runs rendered; service capabilities reported Operational |

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
