"""Project signing of #361 evidence and completed independent mapping reviews."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import Field

from .contracts import StrictModel
from .data_releases import MappingReviewEvidenceV1, sign_mapping_review_evidence
from .facts import CanonicalMappingV1
from .history_replay import (
    ROOT,
    _ensure_tracked_tree_clean,
    _object,
    _resolve_commit,
    _runtime_pins,
    _write_content_addressed,
)
from .serialization import canonical_bytes, sha256_digest

DEFAULT_SIGNER_ID = "value-investment-agent/issue-361-project-signer"
DEFAULT_KEY_PATH = ROOT / ".audit/issue-361-signing/project-signer.pem"
DEFAULT_OUTPUT_DIRECTORY = ROOT / "docs/acceptance/issue-361-signatures-v1"


class ReviewSigningError(ValueError):
    """Invalid signer, review evidence, or signature; no release is published."""


class ProjectSignerV1(StrictModel):
    schema_version: Literal["issue-361-project-signer-v1"] = (
        "issue-361-project-signer-v1"
    )
    signer_id: str = Field(min_length=1)
    algorithm: Literal["Ed25519"] = "Ed25519"
    public_key_base64: str = Field(min_length=1)

    def public_key(self) -> Ed25519PublicKey:
        try:
            return Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.public_key_base64, validate=True)
            )
        except ValueError as error:
            raise ReviewSigningError("invalid project public key") from error


class ProposalSealV1(StrictModel):
    schema_version: Literal["issue-361-unapproved-proposal-seal-v1"] = (
        "issue-361-unapproved-proposal-seal-v1"
    )
    signer: ProjectSignerV1
    subject_schema: str = Field(min_length=1)
    subject_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_status: Literal["unapproved"] = "unapproved"
    independent_review_asserted: Literal[False] = False
    approval_granted: Literal[False] = False
    runtime: dict[str, str]
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(exclude={"signature"}))


def read_document(path: Path) -> dict[str, object]:
    """Read JSON; compressed content-addressed inputs must match their names."""

    content = path.read_bytes()
    if path.suffix == ".gz":
        content = gzip.decompress(content)
    document = _object(json.loads(content), "review document")
    if path.name.endswith(".json.gz"):
        expected = path.name.removesuffix(".json.gz")
        if expected != hashlib.sha256(content).hexdigest() or expected != sha256_digest(
            document
        ):
            raise ReviewSigningError("content-addressed review document mismatch")
    return document


def load_private_key(path: Path) -> Ed25519PrivateKey:
    """Never expose key bytes, accept symlinks, or use a shared-readable key."""

    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise ReviewSigningError("private key must be a regular file with mode 0600")
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ReviewSigningError("project signing requires an Ed25519 private key")
    return key


def initialize_signer(
    path: Path, *, signer_id: str = DEFAULT_SIGNER_ID
) -> tuple[ProjectSignerV1, bool]:
    """Create a persistent key atomically; retries reuse the existing identity."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    wrote = False
    if not path.exists() and not path.is_symlink():
        key = Ed25519PrivateKey.generate()
        content = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        descriptor, temporary = tempfile.mkstemp(prefix=".signer-", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                # link is atomic and refuses replacement if another initializer won.
                os.link(temporary, path)
                wrote = True
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    key = load_private_key(path)
    signer = ProjectSignerV1(
        signer_id=signer_id,
        public_key_base64=base64.b64encode(key.public_key().public_bytes_raw()).decode(
            "ascii"
        ),
    )
    return signer, wrote


def _assert_signer_key(key: Ed25519PrivateKey, signer: ProjectSignerV1) -> None:
    if key.public_key().public_bytes_raw() != signer.public_key().public_bytes_raw():
        raise ReviewSigningError("private key differs from the pinned public identity")


def seal_proposal(
    proposal: dict[str, object],
    *,
    key: Ed25519PrivateKey,
    signer: ProjectSignerV1,
    runtime: dict[str, str],
) -> ProposalSealV1:
    """Authenticate an unapproved package without asserting a mapping review."""

    _assert_signer_key(key, signer)
    schema = proposal.get("schema_version")
    if schema == "sec-issuer-period-mapping-proposals-v1":
        unapproved = (
            proposal.get("approved_mapping_count") == 0
            and proposal.get("reviewer_id") is None
            and proposal.get("review_signature") is None
        )
    elif schema == "historical-market-policy-proposal-v1":
        unapproved = (
            proposal.get("approved_policy_count") == 0
            and proposal.get("approval") is None
            and proposal.get("policy_status") == "proposed_unapproved"
        )
    else:
        raise ReviewSigningError("unsupported proposal schema")
    if not unapproved or proposal.get("supported_history_threshold") is not None:
        raise ReviewSigningError("the seal command accepts unapproved proposals only")
    seal = ProposalSealV1(
        signer=signer,
        subject_schema=str(schema),
        subject_digest=sha256_digest(proposal),
        runtime=runtime,
        signature="0" * 128,
    )
    return seal.model_copy(update={"signature": key.sign(seal.signing_bytes()).hex()})


def sign_completed_mapping_review(
    payload: dict[str, object],
    mapping: CanonicalMappingV1,
    *,
    fixture: bytes,
    key: Ed25519PrivateKey,
    signer: ProjectSignerV1,
) -> MappingReviewEvidenceV1:
    """Sign only a supplied completed review, using the existing release schema."""

    _assert_signer_key(key, signer)
    review = MappingReviewEvidenceV1.model_validate({**payload, "signature": "0" * 128})
    if (
        mapping.status != "approved"
        or mapping.confidence == "unresolved"
        or mapping.reviewer != signer.signer_id
        or mapping.reviewed_at != review.reviewed_at
        or review.reviewer_id != signer.signer_id
        or review.mapping_id != mapping.decision_id
        or review.mapping_digest != sha256_digest(mapping)
    ):
        raise ReviewSigningError(
            "mapping does not match a completed independent review"
        )
    if review.fixture_digest != hashlib.sha256(fixture).hexdigest():
        raise ReviewSigningError("review fixture digest mismatch")
    if not mapping.evidence_refs or not any(
        ref.content_hash == review.fixture_digest for ref in review.evidence_refs
    ):
        raise ReviewSigningError("review must reference the inspected fixture evidence")
    return sign_mapping_review_evidence(payload, key)


def verify_signature(document: dict[str, object], *, signer: ProjectSignerV1) -> str:
    """Verify against an explicitly pinned public identity, never an embedded key."""

    if document.get("schema_version") == "issue-361-unapproved-proposal-seal-v1":
        seal = ProposalSealV1.model_validate(document)
        if seal.signer != signer:
            raise ReviewSigningError("seal signer differs from the pinned identity")
        signing_bytes, signature = seal.signing_bytes(), seal.signature
    else:
        review = MappingReviewEvidenceV1.model_validate(document)
        if review.reviewer_id != signer.signer_id:
            raise ReviewSigningError("reviewer differs from the pinned identity")
        signing_bytes, signature = review.signing_bytes(), review.signature
    try:
        signer.public_key().verify(bytes.fromhex(signature), signing_bytes)
    except InvalidSignature as error:
        raise ReviewSigningError("review signature verification failed") from error
    return sha256_digest(document)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY_PATH)
    parser.add_argument(
        "--output-directory", type=Path, default=DEFAULT_OUTPUT_DIRECTORY
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-key")
    init.add_argument("--signer-id", default=DEFAULT_SIGNER_ID)
    for command in ("seal", "sign-mapping", "verify"):
        child = commands.add_parser(command)
        child.add_argument("--identity", type=Path, required=True)
        child.add_argument("--document", type=Path, required=True)
        if command == "sign-mapping":
            child.add_argument("--mapping", type=Path, required=True)
            child.add_argument("--fixture", type=Path, required=True)
        if command == "verify":
            child.add_argument("--subject", type=Path)
    arguments = parser.parse_args(argv)
    try:
        _ensure_tracked_tree_clean(str(Path(__file__).relative_to(ROOT)))
        runtime = _runtime_pins(_resolve_commit())
        if arguments.command == "init-key":
            signer, key_wrote = initialize_signer(
                arguments.key, signer_id=arguments.signer_id
            )
            result = _write_content_addressed(
                arguments.output_directory, "identities", signer.model_dump()
            )
            print(
                json.dumps({"identity": result, "key_wrote": key_wrote}, sort_keys=True)
            )
            return 0
        signer = ProjectSignerV1.model_validate(read_document(arguments.identity))
        document = read_document(arguments.document)
        if arguments.command == "verify":
            digest = verify_signature(document, signer=signer)
            if arguments.subject is not None:
                seal = ProposalSealV1.model_validate(document)
                if (
                    sha256_digest(read_document(arguments.subject))
                    != seal.subject_digest
                ):
                    raise ReviewSigningError("sealed subject digest mismatch")
            print(json.dumps({"verified": True, "sha256": digest, "runtime": runtime}))
            return 0
        key = load_private_key(arguments.key)
        signed: ProposalSealV1 | MappingReviewEvidenceV1
        if arguments.command == "seal":
            signed = seal_proposal(document, key=key, signer=signer, runtime=runtime)
        else:
            signed = sign_completed_mapping_review(
                document,
                CanonicalMappingV1.model_validate(read_document(arguments.mapping)),
                fixture=arguments.fixture.read_bytes(),
                key=key,
                signer=signer,
            )
        result = _write_content_addressed(
            arguments.output_directory,
            "proposal_seals" if arguments.command == "seal" else "mapping_reviews",
            signed.model_dump(mode="python"),
        )
        print(json.dumps({"artifact": result, "runtime": runtime}, sort_keys=True))
        return 0
    except (ValueError, OSError, EOFError) as error:
        print(f"review signing failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
