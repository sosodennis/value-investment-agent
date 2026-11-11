# Project signing for issue 361

The project signer authenticates evidence bytes. An evidence-package seal explicitly records `review_status=unapproved`, `approval_granted=false`, and `independent_review_asserted=false`. It cannot approve a policy, promote a mapping, activate a data release, or validate a history threshold. Mapping review signing uses the existing `MappingReviewEvidenceV1` contract and requires an already completed, matching independent review.

Run from the clean, committed issue worktree. The command rejects tracked changes before reading keys or writing artifacts. It records the exact commit and runtime pins. Private keys are never printed. The default private key is in the ignored `.audit/issue-361-signing/project-signer.pem`, created with mode 0600. Keep this key when moving or retiring the issue worktree; losing it prevents future signatures from this identity. Do not put it in Git, a report, a Docker image or GitHub.

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service \
  fundamental-history-review-sign init-key
```

Initialization prints the digest-addressed public identity path and `key_wrote`. A second invocation reuses the key and public identity and reports `key_wrote=false` and `wrote=false`. The public identity pins the signer ID and Ed25519 public key; preserve its digest in review evidence. It is a project evidence signer, not an assertion that an independent reviewer has inspected all proposed mappings.

Use the returned public identity to seal a proposal. Replace `IDENTITY` and `PROPOSAL` with the exact paths; do not add an approval field to the proposal.

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service \
  fundamental-history-review-sign seal --identity IDENTITY --document PROPOSAL
```

The subject digest identifies decompressed canonical JSON. Existing compressed inputs must match their content-addressed filenames. Signature bytes are deterministic for the same key, exact commit, runtime pins and subject. Repeating the command reuses the same artifact with `wrote=false`; writes use a temporary file and atomic rename. Verification requires the separately pinned public identity, and can also check the subject:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service \
  fundamental-history-review-sign verify --identity IDENTITY \
  --document SIGNED_SEAL --subject PROPOSAL
```

After actual accounting review, `sign-mapping` accepts a completed canonical mapping, its unsigned `MappingReviewEvidenceV1` payload, and the inspected fixture file:

```sh
UV_CACHE_DIR=/tmp/.uv-cache uv run --project fundamental-service \
  fundamental-history-review-sign sign-mapping --identity IDENTITY \
  --document REVIEW_PAYLOAD --mapping APPROVED_MAPPING --fixture REVIEW_FIXTURE
```

The mapping must already have `status=approved`, resolved confidence, evidence references, and the exact reviewer ID/review time. The payload must have a different author ID, the same reviewer ID/time, the exact mapping ID/canonical digest, and the SHA-256 of the actual fixture bytes. Its evidence references must include that fixture. The script does not edit these fields to make them pass. Fixture changes, an unapproved mapping, mismatched identity or self-review fail before signing.

The resulting mapping signature verifies with the existing release verifier after an authorized operator adds this public identity to that environment's `mapping_reviewers` trust roots. The command does not edit deployment trust roots or make this signer a production authority. Existing development fixture keys are never used. Keep #361 and #369 open until reviewed releases, historical regulatory validation and full replay acceptance pass.
