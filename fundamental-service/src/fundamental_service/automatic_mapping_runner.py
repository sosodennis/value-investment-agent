"""Evaluate, retain and sign automatic mapping decisions without human review."""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from .automatic_mapping import (
    AUTOMATIC_MAPPING_INPUT_ROLE,
    AutomaticMappingRequestV1,
    automatic_mapping_policy_digest,
    evaluate_automatic_mapping,
)
from .command_artifacts import EvidenceArtifactStore, command_artifacts
from .data_releases import (
    ArtifactRefV1,
    DataReleaseError,
    DataReleaseTrustRootsV1,
    ReleaseModel,
    sign_automatic_mapping_approval,
    verify_mapping_review_evidence,
)
from .replay import ArtifactPublicationV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError


class AutomaticMappingReceiptV1(ReleaseModel):
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_publication: ArtifactPublicationV1
    decision_publication: ArtifactPublicationV1
    approval_publication: ArtifactPublicationV1 | None


def approve_mapping(
    request: AutomaticMappingRequestV1,
    *,
    artifacts: EvidenceArtifactStore,
    trust_roots: DataReleaseTrustRootsV1,
    private_key: Ed25519PrivateKey,
) -> AutomaticMappingReceiptV1:
    evaluator = trust_roots.automatic_mapping_evaluators.get(request.evaluator_id)
    if (
        evaluator is None
        or evaluator.policy_digest != automatic_mapping_policy_digest()
        or private_key.public_key().public_bytes_raw()
        != base64.b64decode(evaluator.public_key_ed25519_base64, validate=True)
    ):
        raise DataReleaseError(
            "MAPPING_AUTOMATIC_AUTHORITY_MISMATCH",
            "machine key and executable policy must match deployment trust roots",
        )
    contents = {}
    for ref in request.evidence_refs:
        try:
            record = artifacts.get(ref.artifact_id)
        except SnapshotError as error:
            if error.code == "ARTIFACT_NOT_FOUND":
                continue
            raise
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != ref.media_type
            or record.content_hash != ref.content_hash
        ):
            continue
        try:
            contents[ref.content_hash] = artifacts.read(ref.artifact_id)
        except SnapshotError as error:
            if error.code not in {
                "ARTIFACT_BYTES_UNAVAILABLE",
                "CONTENT_NOT_FOUND",
                "CONTENT_CORRUPT",
                "ARTIFACT_NOT_FOUND",
            }:
                raise
    decision = evaluate_automatic_mapping(request, contents=contents)
    input_digest, output_digest = sha256_digest(request), sha256_digest(decision)
    input_publication = artifacts.put_with_receipt(
        "automatic-mapping-input-" + input_digest,
        request,
        dependency_hashes=tuple(
            sorted({ref.content_hash for ref in request.evidence_refs})
        ),
    )
    decision_publication = artifacts.put_with_receipt(
        "automatic-mapping-decision-" + output_digest,
        decision,
        dependency_hashes=(input_digest, decision.policy_digest),
    )
    approval_publication = None
    if decision.mapping is not None:
        input_ref = ArtifactRefV1(
            artifact_id=input_publication.artifact.artifact_id,
            content_hash=input_publication.artifact.content_hash,
            media_type=input_publication.artifact.media_type,
            role=AUTOMATIC_MAPPING_INPUT_ROLE,
        )
        approval = sign_automatic_mapping_approval(
            {
                "mapping_id": decision.mapping.decision_id,
                "mapping_digest": sha256_digest(decision.mapping),
                "evaluator_id": request.evaluator_id,
                "policy_digest": decision.policy_digest,
                "source_revision": request.source_revision,
                "input_digest": input_digest,
                "output_digest": output_digest,
                "evidence_refs": (input_ref, *request.evidence_refs),
            },
            private_key,
        )
        verify_mapping_review_evidence(approval, trust_roots)
        approval_publication = artifacts.put_with_receipt(
            "automatic-mapping-approval-" + sha256_digest(approval),
            approval,
            dependency_hashes=(input_digest, output_digest, approval.mapping_digest),
        )
    return AutomaticMappingReceiptV1(
        source_revision=request.source_revision,
        input_digest=input_digest,
        output_digest=output_digest,
        input_publication=input_publication,
        decision_publication=decision_publication,
        approval_publication=approval_publication,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--artifacts-root", type=Path)
    parser.add_argument("--trust-roots", type=Path)
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--print-policy-digest", action="store_true")
    args = parser.parse_args(argv)
    if args.print_policy_digest:
        print(automatic_mapping_policy_digest())
        return 0
    if any(
        value is None for value in (args.request, args.trust_roots, args.private_key)
    ):
        parser.error("--request, --trust-roots and --private-key are required")
    try:
        request = AutomaticMappingRequestV1.model_validate_json(
            args.request.read_bytes()
        )
        roots = DataReleaseTrustRootsV1.from_file(args.trust_roots)
        key = serialization.load_pem_private_key(args.private_key.read_bytes(), None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("machine approvals require an Ed25519 key")
        with command_artifacts(args.artifacts_root) as artifacts:
            receipt = approve_mapping(
                request, artifacts=artifacts, trust_roots=roots, private_key=key
            )
    except (DataReleaseError, SnapshotError) as error:
        print(canonical_bytes({"error_code": error.code}).decode(), file=sys.stderr)
        return 2
    except OSError:
        print('{"error_code":"MAPPING_AUTOMATIC_IO_FAILED"}', file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print('{"error_code":"MAPPING_AUTOMATIC_STORAGE_FAILED"}', file=sys.stderr)
        return 2
    except (ValueError, TypeError, UnsupportedAlgorithm):
        print('{"error_code":"MAPPING_AUTOMATIC_INPUT_INVALID"}', file=sys.stderr)
        return 2
    print(canonical_bytes(receipt).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
