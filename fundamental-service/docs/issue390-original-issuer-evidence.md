# Original issuer evidence for operating research

`original-issuer-operating-v1` establishes a bounded issuer claim from original
annual XBRL observations. It exists for historical operating research whose
targets do not use a ticker, share class or per-share price. It does not change
the public ingestion or `original-filing-dei-v1` security identity policy.

`OriginalIssuerIdentityV1` contains the original CIK, registrant name, US-GAAP
reporting basis and USD currency. It has no security or domicile fields and
cannot validate as `IdentityV1` or `SourceSnapshotV1`. The policy requires an
original non-amendment 10-K; canonical SEC CIK/accession/document URI; source and
parser-input hashes; available-at and decision timestamps; an offline parser
with its pinned profile digest; and original DEI observations for CIK, name,
document type, annual period and amendment flag. DEI namespaces, issuer entity
scheme/identifier, consolidated dimensionless annual contexts and aligned
periods must match. Unsupported scope, missing/conflicting facts, future
evidence and source inconsistencies produce retained, stable refusals.

Currency requires current-report-end consolidated, dimensionless monetary
US-GAAP observations for that issuer, unambiguous USD units and at least one
finite observed amount. An unrelated empty or malformed amount does not erase
independent issuer/currency evidence. All such observations remain unchanged
in the complete parser report; no empty value becomes zero. This check grants
no numeric validity, accounting completeness or financial release authority.
Amounts selected for financial calculations still pass the existing mapping,
unit, period, quality and preparation gates.

`OriginalIssuerEvidenceV1` binds the complete report, original metadata, claim,
refusals and policy under canonical input/output digests. Parser fact/finding
order, temporary filing paths and parser execution times do not identify the
claim: the report uses source URI and its explicitly supplied retention/audit
timestamp, and profile paths use the same basename normalization as the pinned
parser profile digest. This timestamp is not a recovered historical HTTP
receipt. Missing HTTP status stays null, and a known non-200 status refuses the
source. Content digests identify supplied evidence; they do not authenticate
its acquisition or reviewer.

`IssuerOperatingSourceV1` is an internal content-addressed source view with one
to six matched, same-identity original filings and distinct accession/source
hashes, all available by its decision timestamp. It retains each complete
original. Changed registrant names are conservatively refused by this version;
a name-change policy is not inferred from CIK alone. Future label originals
must use a separate later view and cannot enter the origin view.

Only the exact operating requirements profile accepts this source view. The
existing annual resolver, historical metrics, forecast composer and operating
projection implement the calculations; this change adds no formula. Canonical
facts must retain the issuer scope, original source hash/URL/role, accession,
availability and non-amendment status. Security-bound, unreviewed or mismatched
inputs are rejected or yield abstention. Full automatic valuation continues to
require its security snapshot and full requirements profile. Every prepared
operating result stays provisional with `supported_history_threshold=null`.

This module performs no acquisition, canonical normalization, signing,
publication, database access or release verification. Like the existing
low-level composer, it assumes its caller has independently authorized the
released financial inputs. The supplied release digest is only a bound
reference. A matched issuer claim explicitly leaves security identity,
domicile, regulatory approval, mapping review and data-release authority
unestablished; even retained blocking regulatory findings are not approval.
Do not count a low-level result as a release-backed empirical forecast.

## Trusted issuer operating releases

`IssuerOperatingReleaseManifestV1` explicitly selects the issuer-only protocol
and pins the complete operating requirements, model, policy, mapping and parser
versions. `IssuerAccountingRoleRuleSetV1` uses the existing accounting evaluator
and an issuer-only protocol with no security ID. The legacy security rule and
release schemas preserve their canonical bytes and security requirements.

`IssuerOperatingReleaseService` publishes an immutable bundle only after the
existing `DataReleaseCanaryRunner` verifies deployment-owned Ed25519 verifier,
workflow and suite trust roots, independent signed mapping reviews, artifact
hashes and the exact original sources. Each original requires retained HTTP200
source metadata, completed offline SEC EFM/DQC validation, a passing bound
integrity artifact, taxonomy manifest and retained raw/parser/index/ZIP bytes.
The same ingestion byte-integrity policy replays those bytes and checks sizes,
archive member and normalization evidence. No HTTP receipt is inferred from an
archive member or a valid signature.

The ingestion converter, accounting evaluator and fact selector regenerate
the declared facts from each complete original report and released mappings.
Changing an amount fails even if the candidate is signed again. Unknown and
unsupported accounting rules retain their dispositions without generating a
numeric placeholder. Complete parser reports retain missing, invalid,
conflicting and excluded observations. Accounting review still belongs to the
trusted independent mapping reviewer.

Publication uses the existing atomic content-addressed artifact store. Reading
requires the exact immutable artifact/manifest pins and reruns current trust,
artifact, original-source and mapping checks before invoking the existing
operating composer. Restart and repeat preserve bytes, digests and mtimes;
duplicate publication returns `wrote=false`. Outputs remain provisional with a
null threshold. This is a library operation for research; it adds no public HTTP
route, production active pointer, acquisition service or review authority.

## Bounded verification and remaining acceptance

The fixed case remains NEWMARKET, CIK `0001282637`, at
`2016-02-12T16:26:17Z`: history accession `0001282637-15-000004`, decision
accession `0001282637-16-000028`, first-original label
`0001282637-17-000005`. Complete original parser reports and exact-commit
checkpoints live outside Git under the retained #376 research evidence root.
No replacement issuer, current ticker directory, fabricated receipt, reviewer
or security identity is used.

Tests cover original namespace/entity/period/currency/refusal boundaries,
malformed and empty observation retention, source and future-label exclusion,
strict contract separation, deterministic order/serialization, operating
numeric parity, and full valuation rejection. Exact-commit reports record the
lock/runtime pins, source/input/output digests, commands and unchanged repeats.
Release tests use explicitly synthetic keys and evidence to cover independent
review, deployment trust rotation, artifact/source swaps, original normalization,
accounting scope, publication/restart and unchanged forecast repeats. These are
contract tests and never count as real SEC release or empirical outcomes. Full
service tests include explicit resource/database skips; those skips do not
establish Docker/service acceptance. No Docker resources are needed for this
internal library increment.

#390, #383 and #376 remain open. Completion still requires service-backed
acceptance of the issuer release path, independent source/semantic review, the four
unresolved accounting roles, actual original-bound forecast/first-label/error
and unchanged repeat, prospective #377 rules, all fixed-100 outcomes and
main/service acceptance. This increment neither closes the study nor approves
a supported history threshold.
