# Fundamental service

This directory contains the independently deployable Fundamental domain service.

Read the [Fundamental service target state](docs/fundamental-enterprise-grade-target-state.md) for the only normative definition of the service's data contracts, model registry, calculations, calibration, provenance, verification, and delivery stages.

Runtime startup, health, auth, deadline, budget, recovery, and Compose checks
are documented in the [operations runbook](docs/operations-runbook.md), which
remains subordinate to the target state.

See [market inputs and replaceable sources](docs/market-input-providers.md) for
the current parameter sources, provider ports, composition points and the
distinction between source admission and financial-policy approval.

Production deployments must set `FUNDAMENTAL_MODEL_TRUST_ROOTS_FILE` to a
read-only deployment-owned JSON file containing verifier IDs, workflow
identities, raw Ed25519 public keys, exact source revisions, and verification
suite digests. Missing roots keep `/readyz` at `not_ready`; malformed roots
fail startup. The operations Compose file uses a development-only public key
fixture and must not be used as a production trust root.

The service will own its source snapshots, point-in-time facts, model definitions, deterministic calculations, calibration artifacts, replay, and cache. The existing agent will call the service through a versioned API after the service passes the release gate for its declared coverage profile. The service must not import the existing agent's private implementation or share its valuation database.

## Frozen annual discovery

The service can freeze an original annual filing catalog from a CIK and valuation
timestamp, using its configured SEC runtime and PostgreSQL/content persistence:

```sh
fundamental-discover-annuals \
  --cik 0000724910 --valuation-timestamp 2025-06-01T00:00:00Z \
  --source-revision <installed-source-commit>
fundamental-discover-annuals --artifact-id annual-discovery:<request-digest>
```

The request pins the selection protocol, issuer, cutoff, original count/lookback,
declared revision and actual configured parser year/form limits. The revision is
an operator declaration; installed-source acceptance checks it independently.
Recent and relevant historical submissions pages are retained before decoding.
The catalog retains all row dispositions, source hashes and refusals. Only
original 10-K acceptance metadata determines eligibility; current ticker metadata
does not establish historical identity. The latest eligible originals are selected
before runtime compatibility is checked, so an unsupported newest original blocks
instead of silently selecting older supported coverage.

Repeats and retrieval verify the immutable request, receipts, original bytes and
reproduced selection, returning the same digest with `wrote=false`. Interrupted or
transient attempts reuse successful captures; retryable failures retain their own
content identities. Catalog evidence does not approve mappings, prove complete
accounting coverage, authorize a release/caller input or calculate a valuation.

Add `--prepare-originals` to capture and strictly validate each selected original
before resolving its security identity from original DEI facts:

```sh
fundamental-discover-annuals \
  --cik 0000724910 --valuation-timestamp 2025-06-01T00:00:00Z \
  --source-revision <installed-source-commit> --prepare-originals
fundamental-discover-annuals --artifact-id original-preparation:<request-digest>
fundamental-discover-annuals --artifact-id original-validation:<request-digest>
```

Validation identities pin the actual Python/Pydantic/Arelle versions, taxonomy
digest, validation profile, configured year/form support and SEC response budgets.
The generic response limit is 24 MB; accession-matched full-submission `.txt`
files have a separate 64 MB limit because they include the filing and exhibits.
Both limits retain bounded reads and deadline enforcement. Both original bytes
and validation receipts are verified on every read. Repeats reuse successful
validation without provider or parser I/O; changing `--ticker` or `--share-class`
reuses the same parsed original. Multiple securities or reused tickers retain a
refusal until an explicit selector matches the original evidence. Inspect the
per-filing validation artifact for original security facts before selecting.

Every selected original and its failure remains in the saved preparation.
Retryable failures retain content-addressed `original-validation-attempt:` and
`original-preparation-attempt:` artifacts without reserving the terminal success
keys. Recovery reuses already captured bytes and completed validations. Terminal
refusals repeat unchanged; new source/runtime inputs require a new request.
This stage publishes no snapshot, mapping, release or valuation.

Parser diagnostics retain the official XULE `effectiveDate` as
`rule_effective_date`, including in saved rejection findings. A missing date,
empty value or official `None` remains unknown; malformed dates refuse with
`DQC_EFFECTIVE_DATE_INVALID`. Missing dates are omitted from serialization so
existing retained evidence keeps its identity. This metadata does not itself
change blocking decisions. Filing-date applicability and official documentation
for rules with no emitted date still require separate validation evidence.

SEC HTML representation profiles preserve the unchanged accession ZIP member.
`sec-edgar-html-tag-line-padding-nbsp-v1` additionally recognizes line-end ASCII
SP/TAB after a tag followed only by exact `&#160;` layout references. It keeps
those character references. The complete direct response must equal the ZIP
member with only the permitted padding removed, one terminal LF appended and
the exact terminal SEC/Akamai script inserted. The accession index must confirm
both the ZIP size and script-free response size, and Akamai response metadata
must match. Any other text, value, entity, byte or metadata difference refuses.
Ordinary tag-ending padding retains its existing profile and evidence identity.

The command can compile these saved originals into the existing automatic
source-plan format with deployment configuration. The configuration contains
`model_id`, `release_profile_id`, `coverage_profile`, `evaluator_id`,
`mapping_version` and `policy_version`; it supplies no company, ticker, accession,
model version or financial values. An optional deployment-owned
`working_capital_recipe_template` contains explicit exclusions and residual
scenarios. Its protocol is
`automatic-source-plan-configuration-v1`. Pin its canonical SHA-256:

```sh
fundamental-discover-annuals \
  --cik 0000724910 --valuation-timestamp 2025-06-01T00:00:00Z \
  --source-revision <installed-source-commit> --prepare-originals \
  --source-plan-configuration /run/config/source-plan.json \
  --configuration-digest <canonical-configuration-sha256>
fundamental-discover-annuals --artifact-id original-source-plan:<request-digest>
```

Compilation verifies the saved original preparation and all original dependencies,
derives identity/accession/date/parser pins from that evidence, and obtains model
versions, requirements and mapping-policy digests from the existing service
registries. It preserves every selected original and refuses the plan if any
original fails or identities conflict. The receipt exposes `plan_ref` for the
saved canonical `AutomaticSourcePreparationPlanV1` consumed by
`fundamental-prepare-source`. Configuration is not approval or authority; the
existing mapping/release/caller gates remain required. Identical compilation and
saved retrieval return the same evidence and `wrote=false` without source/parser
I/O. Interrupted publication reuses completed artifacts; corruption refuses.

When the optional recipe template is present, compilation selects composite
requirements and expands the configured exclusions and explicit asset/liability
scenarios over each validated original's accession and report period. The recipe
pins the service model version, composite requirements digest and configured
mapping version. It has no fact IDs; the existing preparation runner binds it to
acquired canonical facts and retains missing, ambiguous or unsupported evidence
as a refusal. The compiler supplies no default residual fractions or absence
decisions.

An optional deployment-owned `issuer_market_policy_template` pins the
classification and crosswalk provider IDs/versions/digests, reference policy,
risk-free policy and terminal-growth selection policy. When configured, the
compiler derives the `IssuerMarketPreparationRequestV1` issuer, latest original
accession/report period and valuation timestamp from the validated originals.
The resulting plan carries those exact service policy pins into the existing
issuer-market preparation owner; conflicting original identities and
non-USD identities refuse compilation. Templates do not contain market values,
capture receipts, source-use permissions or issuer-specific selections.

The same template pins the source-use policy and provider-neutral capture
templates for nominal GDP, the selected risk-free series, country ERP, industry
beta, pre-tax debt cost and capital weights. URI templates may substitute only
the valuation year or date. Compilation expands them into canonical public
capture and admission requests at the issuer's valuation timestamp; the existing
source acquisition and admission owners retain originals, reproduce providers,
and refuse ineligible or unapproved evidence. The existing market evaluator
enforces completeness of the seven formal composer market roles. This removes
issuer/date request authoring from the caller while keeping provider, source and
policy choices deployment-owned.

The compiler emits requests; the existing formal source-preparation runner
performs their capture and admission. Missing or ineligible sources remain
refusals, and a generated issuer/date request is not evidence that its market
inputs are available or approved.

An existing saved preparation can be compiled with a separately pinned runtime
revision. This verifies and reads retained original artifacts without running
annual discovery or SEC I/O:

```sh
fundamental-discover-annuals \
  --artifact-id original-preparation:<request-digest> \
  --source-revision <installed-source-commit> \
  --source-plan-configuration /run/config/source-plan.json \
  --configuration-digest <canonical-configuration-sha256>
```

The new plan records this current runtime revision separately from each original
validation's historical source revision. The installed runner binds its
automatic authority to the same revision before acquisition.

Without the optional recipe template, this compiler stage uses standard direct
accounting requirements. A compiled source plan alone does not establish complete
valuation inputs; its sources must pass the existing acquisition, admission and
issuer market evaluators.

`fundamental-prepare-issuer` is the company/date entrypoint. It delegates catalog
selection, saved original validation and identity resolution, source-plan
compilation, and execution to the existing service commands and preparation
runner. The deployment still supplies its pinned source-plan configuration and
the existing preparation actor, organization and machine key:

```sh
fundamental-prepare-issuer \
  --cik 0000724910 --valuation-timestamp 2025-06-01T00:00:00Z \
  --source-revision <installed-source-commit> \
  --source-plan-configuration /run/config/source-plan.json \
  --configuration-digest <canonical-configuration-sha256> \
  --actor <operator-id> --organization <authorized-organization> \
  --machine-private-key /run/secrets/mapping-evaluator.pem
```

The canonical result links the annual discovery, original preparation,
source-plan compilation and formal source-preparation receipts by artifact ID
and input/output digest. Incomplete identity/original evidence returns
`status=blocked` with its retained reasons and does not invoke source preparation.
Otherwise `status=preparation_attempted` means the existing runner was called;
inspect its saved artifact for `blocked`, `release_required`,
`approval_required` or `calculated`. This command does not fabricate an approved
release or caller approval. Repeat requests reuse the existing content-addressed
artifacts and return the underlying `wrote=false` dispositions.

For an explicitly current request, add `--current` and supply a recent
`--valuation-timestamp`. This mode requires configured public-source templates.
The existing capture-before-cutoff owner first retains the public originals,
then freezes the effective valuation timestamp at the last capture. Its saved
selection is reused on repeat requests. The result retains the original
`source_plan_ref`, the `effective_source_plan_ref` used by preparation, the
effective timestamp and a `current_source_selection` lineage stage. Failed
captures return their retained issues with `status=blocked` before preparation.
Fixed historical requests keep their exact valuation timestamp.

In current mode, `fundamental-prepare-source` also returns the typed
`current_selection` and `current_selection_publication`. The issuer entrypoint
checks that selection against its compiled template and verifies the preparation
receipt references the effective plan. This freezes source availability; market
admission, trusted release and exact-input caller approval still run through the
existing owners.

An optional `quote_source_template` in the source-plan configuration supplies
the deployment's quote provider URI template, terms templates and source-use
policy version/digest. Its `request.protocol` is
`automatic-us-common-previous-weekday-quote-template-v1`. The credential-free
`request.uri_template` must contain `{security_id}` and either
`{observation_date}` or both `{observation_start_epoch}` and
`{observation_end_epoch}`. Epoch values delimit the New York calendar day in
UTC seconds, with an exclusive end.
The compiler takes the security from the verified SEC identity and selects the
preceding complete weekday in New York. Weekends are excluded; holidays are
not inferred. If that date has no provider observation, the existing capture or
admission owner retains its refusal without substituting a price or date.
The template supports USD securities. It emits the same public capture and
exact quote-admission requests used by the existing runner, sharing identical
terms captures with market inputs. Conflicting capture profiles refuse.
The configuration grants no source-use rights. Deployment needs an approved
policy covering the intended use and any credential required by that provider.

The quote reproduction registry also accepts retained Yahoo chart bytes under
`yahoo-us-equity-latest-completed-daily-close-capture-v1`. This profile preserves
the numeric `indicators.quote.close` token as a decimal, ignores `adjclose`, and
requires the selected day to match both the final daily bar and the provider's
latest regular-market trade. It supports USD equities on Nasdaq or NYSE and
requires capture after the New York calendar day ends. Availability is the actual
capture time, so it cannot establish an earlier historical information set.
Yahoo's older history is split-adjusted even when yfinance uses
`auto_adjust=False`; this profile refuses earlier sessions and subsequent split
events instead of claiming to reconstruct an unadjusted historical price.
The preparation HTTP adapter registers the same bounded Yahoo chart profile
and exact Yahoo terms URI. Capture requires one deployment source-use rule
covering valuation preparation before HTTP I/O. It needs no API key, refuses
redirects and responses over 1 MiB, and reuses saved captures without I/O.
Source-use admission separately checks the retained terms and policy. The
built-in free market policy contains no Yahoo authorization.

## Source preparation command

The acquisition owner also accepts `AutomaticSecIngestionRequestV1` with exact
model, requirements, executable mapping policy, source revision and evaluator
pins. It has no manual mapping references. An injected deployment authority
validates these pins before source I/O. After original integrity, EFM/DQC and
historical DEI validation, ingestion invokes the existing automatic mapping batch,
retains every decision/certificate/refusal and normalizes accepted mappings with
the existing fact functions. An incomplete acquisition remains abstained.
The installed command accepts this mapping-free source request through
`AutomaticSourcePreparationPlanV1`, protocol `automatic-source-preparation-v1`:

```sh
fundamental-prepare-source \
  --plan automatic-source-plan.json --plan-digest <canonical-plan-sha256> \
  --machine-private-key /run/secrets/mapping-evaluator.pem \
  --runtime-source-revision <installed-source-commit> \
  --actor <operator-id> --organization <authorized-organization>
```

Deployment trust roots must authorize the matching evaluator/key and executable
policy. The independently supplied runtime revision must match the plan. Each
original pins the complete model requirements; missing roles retain the complete
mapping batch and keep preparation blocked. A repeat reads completed acquisitions
without provider/parser I/O. Supported mappings are read from those immutable
batches for release comparison, using the existing release and caller gates.

`fundamental-prepare-source` coordinates source acquisition, trusted release
activation and the existing automatic composer outside the serving API request
path. Run it with the service's configured PostgreSQL, content volume, SEC
validation assets and trust roots:

```sh
fundamental-prepare-source \
  --plan approved-source-plan.json --plan-digest <canonical-plan-sha256> \
  --actor <operator-id> --organization <authorized-organization>
```

The versioned `SourcePreparationPlanV2` pins a source revision, release profile,
model and one to six `SecIngestionRequestV1` values in `ingestions`. Their field
union must cover the complete model requirements. Multiple requests must pin
distinct original 10-K accessions in sorted order, with the same issuer, valuation
date and runtime profile. Each request may map only the roles supported by that
filing. Its digest is SHA-256 over the service's
canonical serialization. The command first resolves released evidence. On a miss,
it uses existing SEC acquisition and retention; an already stored snapshot can be
used with `--candidate <trusted-candidate.json>` without another acquisition.
Candidate publication and activation require the configured organizations, release
verification and trusted automatic mapping approval or retained human review.
The manual plan uses existing mapping decisions. Automatic plans evaluate new
mappings through the deployment's trusted machine authority; release approval
remains a separate operation.

Reuse also checks the plan's mapping decision IDs, versions and financial roles
against the immutable release, and each declared fact against the mapping pinned
for its original accession and role. A release containing another reviewed mapping
does not authorize substituting it. Changed mapping or fact bytes fail as corrupt
evidence before any new acquisition or calculation.

For several originals, the service publishes a deterministic history snapshot
that references each immutable component and its own integrity evidence. It does
not copy or change facts. Release validation, serving and backup verification
re-read those components; a missing or changed original refuses the history.
Repeating composition reuses the same snapshot without provider I/O. History
sufficiency remains the formal #352 composer's decision.

[Accounting role evidence](docs/accounting-role-evidence.md) distinguishes direct
observations, source-bound accounting classifications, explicitly reviewed absence
and unresolved roles. It preserves the original observations and existing release
review/approval boundaries.

`fundamental-approve-mapping` evaluates retained SEC originals using the
versioned machine policy and a deployment-owned Ed25519 key. A complete
`AutomaticMappingBatchRequestV1` generates every exact model role, retaining
approved and abstained decisions in canonical order. The source evidence,
policy digest and trusted evaluator must match; repeated commands reuse the
same artifacts. [Automatic approval policy](docs/operations-runbook.md#automatic-mapping-approval)
documents the command and supported disclosure limits. AI verification remains
future work.

The canonical JSON receipt contains an artifact reference and `wrote`. Read its
metadata and bytes through the authenticated `/v1/artifacts/{artifact_id}` and
`/v1/artifacts/{artifact_id}/content` endpoints. Identical evidence is reused with
`wrote=false`; corrupt or conflicting evidence fails without replacement.

The stored outcome is `release_required` for an acquired but unreleased snapshot,
`blocked` for retained evidence failures, or `approval_required` when the formal
composer prepares an input. To calculate, pass `--approval <approval.json>` with
the caller's explicit approval of that exact prepared input digest. `calculated`
retains the existing calculator's uncertainty report and provenance. The command
does not own a valuation session or job, and it never manufactures caller approval.

The #361 complete-flow acceptance remains pending. Synthetic fixtures prove
coordination and persistence mechanics; they do not certify real issuer mappings,
multi-filing coverage or end-to-end original-filing numerical success. History
thresholds remain null, and supported calculations remain provisional where the
existing composer requires that disposition.

The service consumes the shared `internal.v1` context from
`finance-agent-core/src/shared/internal_services` through the supported Docker
additional build context. Its operation payloads are `{context, input}` and its
responses carry shared correlation/error metadata around a service-owned
`fundamental.v1` result. It never imports agent implementation modules or reads
the agent database/cache.

The Docker image limits native BLAS/OpenMP execution to one thread and glibc to
two allocation arenas. These defaults reduce virtual address reservations inside
the SEC parser's child memory budget; they do not change its memory ceiling,
validation rules or parser concurrency. Full DQC rulesets still need an explicit
deployment memory budget sized for the pinned taxonomy and ruleset. Inspect the
retained validation outcome: a completed parser can still reject a filing.

The parent integration branch is `codex/issue-270-integration` and its dedicated worktree is `../value-investment-agent-issue-270-integration`. Child changes are delivered serially from that tip according to `docs/issue-worktree-lifecycle.md`.

## Independent verification

The fixed release cohort is replayed entirely from captured SEC bytes. It does
not perform provider access:

```sh
uv run --python 3.12 python -m fundamental_service.verification_gate \
  --cohort tests/fixtures/verification/golden_cohort.json \
  --report /tmp/fundamental-verification-report.json
```

The gate compares the production graph with equations maintained in
`src/fundamental_service/verification.py`, checks node tolerances and formula
invariants, exercises monotonicity/metamorphic and mutation sentinels, and
requires machine-readable reasons and missing evidence for every abstention or
degraded case. The engineering cohort is replay evidence only; it is never
used as calibration ground truth.

## Operations verification

The isolated container uses
`compose/verification/docker-compose.issue280-operations.yml` with project
`value-investment-agent-270-integration`. It owns a project-scoped named volume
for snapshots, content, and released artifacts and does not start the unrelated
repository-wide stack.

Incomplete source plans retain a canonical `source_outcomes` entry for every
requested original, in plan order. Each entry binds the request digest and
accession to its snapshot/digest, quality and missing-evidence diagnostics.
Nonretryable source/evidence refusals allow remaining originals to be assessed;
any incomplete acquisition keeps the report blocked and prevents history
composition, release activation and calculation. Authorization, retryable and
transport failures still propagate. Correlation IDs and created/reused transport
status are excluded from this evidence, so cache reuse preserves report identity.

New runner reports also retain `source_plan_ref`, an immutable artifact reference
to the complete canonical source plan. Its content hash equals `plan_digest`.
Read it through the existing artifact metadata/content endpoints to reconstruct
the exact requests, including requests whose acquisition failed before publishing
a snapshot. Identical runs reuse both the input plan and output report.

### Full DQC rulesets for multiple taxonomy years

`FUNDAMENTAL_SEC_DQC_RULESET_CATALOG_PATH` optionally names a deployment JSON
catalog. Bind-mount the catalog and its official full DQC v31.0.3 ruleset files
read-only. Each catalog binding contains `taxonomy_namespace`, `path`, and
`sha256`. The catalog protocol is `dqc-us-full-ruleset-catalog-v1`; its
`dqc_version` is `v31.0.3`. Sort bindings by namespace and use unique filenames.
Capture the files from a pinned official DataQualityCommittee release commit.
Keep the original bytes and capture receipts outside Git.

The runtime verifies every file hash. After Arelle loads the original DTS, it
selects the one exact US GAAP namespace binding and runs the full ruleset with
strict EFM validation. Missing, mixed or unbound namespaces refuse. The profile
digest includes the catalog and file hashes; the report records the selected
namespace and hash, and serving requires that evidence. An empty setting keeps
the existing single-ruleset profile. Adding supported filing years requires
matching taxonomy dependencies and rulesets; changing the year list alone does
not establish support. This setting grants no source-use permission or caller
approval.
