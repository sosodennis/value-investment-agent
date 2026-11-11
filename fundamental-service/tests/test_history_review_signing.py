"""Signing fixtures are engineering evidence, never production mapping approval."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fundamental_service import history_review_signing as signing
from fundamental_service.data_releases import (
    DataReleaseTrustRootsV1,
    DataReleaseVerifierV1,
    verify_mapping_review_evidence,
)
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.history_replay import _write_content_addressed
from fundamental_service.serialization import canonical_bytes, sha256_digest


def _proposal() -> dict[str, object]:
    return {
        "schema_version": "sec-issuer-period-mapping-proposals-v1",
        "approved_mapping_count": 0,
        "reviewer_id": None,
        "review_signature": None,
        "supported_history_threshold": None,
        "issuer_rows": [{"cik": "0001539778", "disposition": "requires_review"}],
    }


def _mapping_review(
    signer: signing.ProjectSignerV1,
) -> tuple[CanonicalMappingV1, dict[str, object], bytes]:
    fixture = b"synthetic inspected filing/context/period/sign evidence"
    fixture_digest = hashlib.sha256(fixture).hexdigest()
    reviewed_at = datetime(2026, 11, 10, tzinfo=UTC)
    mapping = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id="fixture-revenue-decision",
        source_concept="us-gaap:Revenues",
        normalized_field="revenue",
        mapping_version="fixture-mapping-v1",
        confidence="high",
        evidence_refs=(fixture_digest,),
        reviewer=signer.signer_id,
        reviewed_at=reviewed_at,
        status="approved",
    )
    review: dict[str, object] = {
        "mapping_id": mapping.decision_id,
        "mapping_digest": sha256_digest(mapping),
        "author_id": "fixture-author",
        "reviewer_id": signer.signer_id,
        "reviewed_at": reviewed_at,
        "fixture_digest": fixture_digest,
        "evidence_refs": (
            {
                "artifact_id": "fixture-audit",
                "content_hash": fixture_digest,
                "media_type": "text/plain",
                "role": "mapping-review-evidence",
            },
        ),
    }
    return mapping, review, fixture


def test_key_initialization_reuses_identity_bytes_and_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "signer.pem"
    signer, wrote = signing.initialize_signer(path)
    before = path.stat()
    content = path.read_bytes()
    repeat, repeated_write = signing.initialize_signer(path)
    assert wrote is True and repeated_write is False
    assert signer == repeat
    assert path.read_bytes() == content
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    with pytest.raises(signing.ReviewSigningError, match="0600"):
        signing.load_private_key(path)
    path.chmod(0o600)
    link = tmp_path / "alias.pem"
    link.symlink_to(path)
    with pytest.raises(signing.ReviewSigningError, match="regular file"):
        signing.initialize_signer(link)


def test_seal_is_deterministic_unapproved_and_cannot_change_review_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "key.pem"
    signer, _ = signing.initialize_signer(path)
    key = signing.load_private_key(path)
    proposal = _proposal()
    before = canonical_bytes(proposal)
    seal = signing.seal_proposal(
        proposal, key=key, signer=signer, runtime={"commit": "a"}
    )
    repeat = signing.seal_proposal(
        proposal, key=key, signer=signer, runtime={"commit": "a"}
    )
    assert seal == repeat
    assert seal.approval_granted is seal.independent_review_asserted is False
    assert seal.review_status == "unapproved"
    assert seal.subject_digest == sha256_digest(proposal)
    assert canonical_bytes(proposal) == before
    signing.verify_signature(seal.model_dump(), signer=signer)
    first = _write_content_addressed(tmp_path, "seals", seal.model_dump())
    artifact = Path(first["path"])
    original = artifact.read_bytes(), artifact.stat().st_mtime_ns
    second = _write_content_addressed(tmp_path, "seals", repeat.model_dump())
    assert second["wrote"] is False
    assert (artifact.read_bytes(), artifact.stat().st_mtime_ns) == original
    tampered = seal.model_dump()
    tampered["subject_digest"] = "b" * 64
    with pytest.raises(signing.ReviewSigningError, match="verification failed"):
        signing.verify_signature(tampered, signer=signer)
    with pytest.raises(signing.ReviewSigningError, match="unapproved proposals only"):
        signing.seal_proposal(
            {**proposal, "approved_mapping_count": 1},
            key=key,
            signer=signer,
            runtime={},
        )


def test_signer_identity_is_pinned_outside_the_signed_document(tmp_path: Path) -> None:
    signer, _ = signing.initialize_signer(tmp_path / "key.pem")
    key = signing.load_private_key(tmp_path / "key.pem")
    seal = signing.seal_proposal(_proposal(), key=key, signer=signer, runtime={})
    other, _ = signing.initialize_signer(tmp_path / "other.pem")
    with pytest.raises(signing.ReviewSigningError, match="pinned identity"):
        signing.verify_signature(seal.model_dump(), signer=other)
    with pytest.raises(signing.ReviewSigningError, match="pinned public identity"):
        signing.seal_proposal(
            _proposal(), key=Ed25519PrivateKey.generate(), signer=signer, runtime={}
        )


def test_completed_review_signature_passes_existing_release_contract(
    tmp_path: Path,
) -> None:
    signer, _ = signing.initialize_signer(tmp_path / "key.pem")
    key = signing.load_private_key(tmp_path / "key.pem")
    mapping, payload, fixture = _mapping_review(signer)
    review = signing.sign_completed_mapping_review(
        payload, mapping, fixture=fixture, key=key, signer=signer
    )
    repeat = signing.sign_completed_mapping_review(
        payload, mapping, fixture=fixture, key=key, signer=signer
    )
    assert review == repeat
    roots = DataReleaseTrustRootsV1(
        verifiers={
            "fixture-verifier": DataReleaseVerifierV1(
                workflow_identity="fixture-only",
                public_key_ed25519_base64=signer.public_key_base64,
                verification_suite_digest="a" * 64,
            )
        },
        mapping_reviewers={signer.signer_id: signer.public_key_base64},
    )
    verify_mapping_review_evidence(review, roots)
    signing.verify_signature(review.model_dump(), signer=signer)


@pytest.mark.parametrize(
    "defect", ["author", "reviewer", "digest", "fixture", "unreviewed"]
)
def test_invalid_or_incomplete_mapping_review_is_not_signed(
    tmp_path: Path, defect: str
) -> None:
    signer, _ = signing.initialize_signer(tmp_path / "key.pem")
    key = signing.load_private_key(tmp_path / "key.pem")
    mapping, payload, fixture = _mapping_review(signer)
    if defect == "author":
        payload["author_id"] = signer.signer_id
    elif defect == "reviewer":
        payload["reviewer_id"] = "another-reviewer"
    elif defect == "digest":
        payload["mapping_digest"] = "b" * 64
    elif defect == "fixture":
        fixture += b"changed"
    else:
        mapping = mapping.model_copy(update={"status": "provisional"})
    with pytest.raises(ValueError):
        signing.sign_completed_mapping_review(
            payload, mapping, fixture=fixture, key=key, signer=signer
        )


def test_cli_initializes_seals_and_verifies_subject_without_exposing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(signing, "_ensure_tracked_tree_clean", lambda _: None)
    key = tmp_path / "signer.pem"
    common = ["--key", str(key), "--output-directory", str(tmp_path)]
    assert signing.main([*common, "init-key"]) == 0
    initialized = json.loads(capsys.readouterr().out)
    identity = initialized["identity"]["path"]
    subject = tmp_path / "subject.json"
    subject.write_bytes(canonical_bytes(_proposal()))
    assert (
        signing.main(
            [*common, "seal", "--identity", identity, "--document", str(subject)]
        )
        == 0
    )
    sealed_output = capsys.readouterr().out
    artifact = json.loads(sealed_output)["artifact"]["path"]
    assert "PRIVATE KEY" not in sealed_output
    verify = [
        *common,
        "verify",
        "--identity",
        identity,
        "--document",
        artifact,
        "--subject",
        str(subject),
    ]
    assert signing.main(verify) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True
    subject.write_text('{"tampered":true}')
    assert signing.main(verify) == 1
    assert "subject digest mismatch" in capsys.readouterr().err
    document = json.loads(gzip.decompress(Path(artifact).read_bytes()))
    assert document["approval_granted"] is False


def test_cli_rejects_dirty_source_before_key_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dirty(_: str) -> None:
        raise ValueError("source must be clean")

    monkeypatch.setattr(signing, "_ensure_tracked_tree_clean", dirty)
    key = tmp_path / "never-created.pem"
    assert signing.main(["--key", str(key), "init-key"]) == 1
    assert not key.exists()
