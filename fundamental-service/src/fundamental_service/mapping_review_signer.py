"""Sign an existing independent mapping review against deployment trust roots."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field

from .data_releases import (
    DataReleaseError,
    DataReleaseTrustRootsV1,
    MappingReviewStatementV1,
    ReleaseModel,
    sign_mapping_review_evidence,
    verify_mapping_review_evidence,
)
from .facts import CanonicalMappingV1
from .replay import ArtifactPublicationV1, ArtifactStore
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError


class MappingReviewSigningReceiptV1(ReleaseModel):
    source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    publication: ArtifactPublicationV1


def sign_review(
    *,
    statement_path: Path,
    mapping_path: Path,
    fixture_path: Path,
    artifacts_root: Path,
    trust_roots_path: Path,
    private_key_path: Path,
    source_revision: str,
) -> MappingReviewSigningReceiptV1:
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("source_revision must be an exact commit")
    statement = MappingReviewStatementV1.model_validate_json(
        statement_path.read_bytes()
    )
    mapping = CanonicalMappingV1.model_validate_json(mapping_path.read_bytes())
    roots = DataReleaseTrustRootsV1.from_file(trust_roots_path)
    if mapping.status != "approved":
        raise DataReleaseError(
            "MAPPING_REVIEW_NOT_APPROVED", "mapping must already be approved"
        )
    if (
        mapping.decision_id != statement.mapping_id
        or sha256_digest(mapping.model_dump(mode="json")) != statement.mapping_digest
        or mapping.reviewer != statement.reviewer_id
        or mapping.reviewed_at != statement.reviewed_at
    ):
        raise DataReleaseError(
            "MAPPING_REVIEW_MAPPING_MISMATCH", "review does not match mapping"
        )
    fixture: object = json.loads(fixture_path.read_bytes())
    if sha256_digest(fixture) != statement.fixture_digest:
        raise DataReleaseError(
            "MAPPING_REVIEW_FIXTURE_MISMATCH", "review fixture digest differs"
        )
    trusted_key = roots.mapping_reviewer_public_key(statement.reviewer_id)
    if trusted_key is None:
        raise DataReleaseError(
            "DATA_RELEASE_MAPPING_REVIEWER_UNTRUSTED", "reviewer is not trusted"
        )
    key = serialization.load_pem_private_key(
        private_key_path.read_bytes(), password=None
    )
    if (
        not isinstance(key, Ed25519PrivateKey)
        or key.public_key().public_bytes_raw() != trusted_key
    ):
        raise DataReleaseError(
            "MAPPING_REVIEW_KEY_MISMATCH", "private key differs from trusted reviewer"
        )
    store = ArtifactStore(artifacts_root)
    for ref in statement.evidence_refs:
        record = store.get(ref.artifact_id)
        if (
            record.status != "valid"
            or record.retention != "evidence"
            or record.media_type != ref.media_type
            or record.content_hash != ref.content_hash
        ):
            raise DataReleaseError(
                "MAPPING_REVIEW_EVIDENCE_MISMATCH", "retained review evidence differs"
            )
        store.read(ref.artifact_id)
    review = sign_mapping_review_evidence(statement.model_dump(mode="python"), key)
    verify_mapping_review_evidence(review, roots)
    output_digest = sha256_digest(review)
    input_digest = sha256_digest(
        {
            "protocol": "mapping-review-signing-v1",
            "source_revision": source_revision,
            "statement": statement,
            "trust_roots_digest": sha256_digest(roots),
        }
    )
    publication = store.put_with_receipt(
        f"mapping-review-{output_digest}",
        review,
        dependency_hashes=(
            statement.mapping_digest,
            statement.fixture_digest,
            *(ref.content_hash for ref in statement.evidence_refs),
        ),
    )
    return MappingReviewSigningReceiptV1(
        source_revision=source_revision,
        input_digest=input_digest,
        output_digest=output_digest,
        publication=publication,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--statement", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--trust-roots", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = sign_review(
            statement_path=args.statement,
            mapping_path=args.mapping,
            fixture_path=args.fixture,
            artifacts_root=args.artifacts_root,
            trust_roots_path=args.trust_roots,
            private_key_path=args.private_key,
            source_revision=args.source_revision,
        )
    except (DataReleaseError, SnapshotError) as exc:
        print(canonical_bytes({"error_code": exc.code}).decode(), file=sys.stderr)
        return 2
    except OSError:
        print('{"error_code":"MAPPING_REVIEW_IO_FAILED"}', file=sys.stderr)
        return 2
    except (ValueError, TypeError, UnsupportedAlgorithm):
        print('{"error_code":"MAPPING_REVIEW_INPUT_INVALID"}', file=sys.stderr)
        return 2
    print(canonical_bytes(receipt).decode())
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by CLI subprocess
    raise SystemExit(main())
