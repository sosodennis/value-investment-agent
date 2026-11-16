# Source-bound accounting-field observations

Fundamental Service owns `AccountingFieldRequestV1`,
`AccountingFieldExtractionV1` and `extract_accounting_fields` in
`fundamental_service.accounting_fields`. They assemble reviewable observations
from one original filing. They do not select canonical financial inputs,
classify unknown balances, approve mappings, publish releases or calculate
valuation formulas.

This implements the existing target-state requirements for source, period,
unit and scope traceability. It reuses `automatic_mapping_proposals` and
`parsed_facts_to_candidates`; the registered accounting rules and approval
policies retain their ownership and executable digests. There is no issuer-
or year-specific branch in the new extractor.

## Inputs and consumers

The request contains an `OriginalIssuerEvidenceV1`, distinct normalized field
names and a mapping version. Omit `mappings` to enumerate existing registered
proposals. Supply mappings to replay precisely those decisions; their fields
and versions must match. An empty supplied tuple means no supplied mappings,
not permission to fall back to other concepts. Copied Pydantic objects are
revalidated, including original evidence identities and digests.

`batch_history_study.py` uses registered proposals for the nine core/parent
roles. Its protocol is `fixed100-original-candidate-batch-v2` because the
packet contract and policy pins have changed. Existing v1 evidence remains
immutable. `compile_transition_disclosures.py` uses its exact observation-
scoped mappings to retain original text through the same entrypoint. Its
existing disclosure eligibility and conditional-model rules still apply.
Other service callers can use this contract without a research dependency.

## Output and limits

Each requested field remains present with its proposals, typed candidates,
count, missing/error codes, per-mapping extraction failures and value
conflicts. Candidates retain the formal converter's period, unit, currency,
scale, dimensions, issuer/security/consolidation scope, accession, amendment,
availability, source hash, context and mapping/accounting evidence. Existing
computed mappings retain their source-bound assumptions in accounting
evidence; direct observations acquire no invented allocation assumptions.

Conflicts identify unequal values at the same reported field, period, unit,
scale, currency, dimensions and scope, including declared concept
alternatives. This is a review signal, not an accounting equivalence claim or
the canonical `FACT_CONFLICT` selection decision. Different scales are not
converted or netted here. No candidate is chosen by this operation. Dimensioned,
nonannual or otherwise inadmissible candidates remain visible; the formal
mapping/selection owners determine whether they are usable.

All observations excluded by the existing converter remain in the original
report addressed by `original_evidence_digest`. An empty result says that no
source-bound candidate was produced, not that the balance is zero or the
role inapplicable. Original refusals and parser blockers retain their codes;
the original report preserves findings and severity.

The result's authority is always
`provisional_candidates_not_approved_mapping_or_model_inputs`, including when
a caller supplies an approved mapping. Canonical selection, accounting
adjudication, trusted review, release integrity and model requirements remain
separate gates. This extraction cannot change quality or establish a history
threshold.

## Replay a packet

Save a canonical `AccountingFieldRequestV1` outside Git, then run from a clean
implementation checkout with the pinned Fundamental runtime:

```sh
PYTHONPATH=fundamental-service/src:scripts python -B scripts/extract_accounting_fields.py \
  --request /absolute/evidence/request.json \
  --request-digest <sha256-of-request-bytes> \
  --exact-commit <full-clean-commit> \
  --output-directory /absolute/evidence/field-packets
```

The tool checks the exact commit, request hash and canonical encoding. Its
report records runtime pins, request/extraction inputs and output digests.
The extraction pins its own executable source plus the existing mapping
policy. Code pin reads are the only extraction I/O; no network, database,
signing, snapshot publication, current ticker or market data is used.

The existing report writer requires storage outside any Git checkout. It
locks publication, verifies existing bytes and writes new artifacts through
a temporary file and atomic rename. Repeat the exact command: the report
digest must match and `wrote` must be `false`, with unchanged artifact bytes,
sizes and mtimes. Invalid input or a corrupt existing artifact fails closed.

Multi-issuer evidence and exact validation commands belong in the pull
request and external evidence index. Candidate coverage is not the number of
completed forecast/label/error cases. #376 and #377 remain open until their
separate empirical and review gates pass.
