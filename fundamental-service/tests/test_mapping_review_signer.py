from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from fundamental_service.data_releases import (
    DataReleaseTrustRootsV1,
    MappingReviewEvidenceV1,
    MappingReviewStatementV1,
    sign_mapping_review_evidence,
    verify_mapping_review_evidence,
)
from fundamental_service.facts import CanonicalMappingV1
from fundamental_service.mapping_review_signer import main
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest


# These fixed keys authorize synthetic test evidence only.
SYNTHETIC_REVIEW_KEY = Ed25519PrivateKey.from_private_bytes(b"s" * 32)
REVISION = "1" * 40


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_bytes(value))


def _write_key(path: Path, key: Ed25519PrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )


def _inputs(tmp_path: Path) -> dict[str, Path]:
    paths = {
        name: tmp_path / name
        for name in (
            "statement",
            "mapping",
            "fixture",
            "artifacts-root",
            "trust-roots",
            "private-key",
        )
    }
    evidence = ArtifactStore(paths["artifacts-root"]).put(
        "synthetic-disclosure", {"disclosure": "synthetic review evidence"}
    )
    mapping = CanonicalMappingV1.model_validate(
        {
            "contract_version": "fundamental.v1",
            "decision_id": "synthetic-revenue-v1",
            "source_concept": "us-gaap:Revenues",
            "normalized_field": "revenue",
            "mapping_version": "synthetic-v1",
            "confidence": "high",
            "reviewer": "synthetic-reviewer",
            "reviewed_at": "2026-01-02T00:00:00Z",
            "status": "approved",
        }
    )
    fixture = {"case": "synthetic-only", "revenue": "100"}
    statement = {
        "mapping_id": mapping.decision_id,
        "mapping_digest": sha256_digest(mapping.model_dump(mode="json")),
        "author_id": "synthetic-author",
        "reviewer_id": mapping.reviewer,
        "reviewed_at": mapping.reviewed_at,
        "evidence_refs": (
            {
                "artifact_id": evidence.artifact_id,
                "content_hash": evidence.content_hash,
                "media_type": evidence.media_type,
                "role": "mapping-review",
            },
        ),
        "fixture_digest": sha256_digest(fixture),
    }
    roots = {
        "verifiers": {
            "synthetic-verifier": {
                "workflow_identity": "test://synthetic-only",
                "public_key_ed25519_base64": base64.b64encode(
                    SYNTHETIC_REVIEW_KEY.public_key().public_bytes_raw()
                ).decode(),
                "verification_suite_digest": "a" * 64,
            }
        },
        "mapping_reviewers": {
            "synthetic-reviewer": base64.b64encode(
                SYNTHETIC_REVIEW_KEY.public_key().public_bytes_raw()
            ).decode()
        },
    }
    for name, value in (
        ("mapping", mapping),
        ("fixture", fixture),
        ("statement", statement),
        ("trust-roots", roots),
    ):
        _write_json(paths[name], value)
    _write_key(paths["private-key"], SYNTHETIC_REVIEW_KEY)
    return paths


def _argv(paths: dict[str, Path]) -> list[str]:
    return [
        argument
        for name, path in paths.items()
        for argument in (f"--{name}", str(path))
    ] + ["--source-revision", REVISION]


def _file_inventory(root: Path) -> dict[str, tuple[str, int]]:
    return {
        str(path.relative_to(root)): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def test_cli_signs_existing_review_and_reuses_it_across_processes(
    tmp_path: Path,
) -> None:
    paths = _inputs(tmp_path)
    command = [
        sys.executable,
        "-m",
        "fundamental_service.mapping_review_signer",
        *_argv(paths),
    ]
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "src"))
    first = subprocess.run(command, env=environment, capture_output=True, check=True)
    receipt = json.loads(first.stdout)
    assert not first.stderr
    assert receipt["source_revision"] == REVISION
    assert receipt["publication"]["wrote"] is True
    store = ArtifactStore(paths["artifacts-root"])
    signed_bytes = store.read(receipt["publication"]["artifact"]["artifact_id"])
    review = MappingReviewEvidenceV1.model_validate_json(signed_bytes)
    roots = DataReleaseTrustRootsV1.from_file(paths["trust-roots"])
    verify_mapping_review_evidence(review, roots)
    unsigned = MappingReviewStatementV1.model_validate_json(
        paths["statement"].read_bytes()
    )
    legacy = sign_mapping_review_evidence(
        unsigned.model_dump(mode="python"), SYNTHETIC_REVIEW_KEY
    )
    assert signed_bytes == canonical_bytes(legacy)
    assert review.signing_bytes() == canonical_bytes(unsigned)
    assert receipt["output_digest"] == hashlib.sha256(signed_bytes).hexdigest()
    assert receipt["publication"]["artifact"]["retention"] == "evidence"
    before = _file_inventory(tmp_path)
    for _ in range(2):
        repeated = subprocess.run(
            command, env=environment, capture_output=True, check=True
        )
        assert not repeated.stderr
        expected = {
            **receipt,
            "publication": {**receipt["publication"], "wrote": False},
        }
        assert json.loads(repeated.stdout) == expected
        assert _file_inventory(tmp_path) == before


@pytest.mark.parametrize(
    ("change", "error_code"),
    [
        ("mapping_digest", "MAPPING_REVIEW_MAPPING_MISMATCH"),
        ("mapping_id", "MAPPING_REVIEW_MAPPING_MISMATCH"),
        ("reviewer_mismatch", "MAPPING_REVIEW_MAPPING_MISMATCH"),
        ("review_time", "MAPPING_REVIEW_MAPPING_MISMATCH"),
        ("provisional", "MAPPING_REVIEW_NOT_APPROVED"),
        ("self_review", "MAPPING_REVIEW_INPUT_INVALID"),
        ("untrusted", "DATA_RELEASE_MAPPING_REVIEWER_UNTRUSTED"),
        ("fixture", "MAPPING_REVIEW_FIXTURE_MISMATCH"),
        ("key", "MAPPING_REVIEW_KEY_MISMATCH"),
        ("invalid_key", "MAPPING_REVIEW_INPUT_INVALID"),
        ("key_missing", "MAPPING_REVIEW_IO_FAILED"),
        ("evidence_hash", "MAPPING_REVIEW_EVIDENCE_MISMATCH"),
        ("evidence_media", "MAPPING_REVIEW_EVIDENCE_MISMATCH"),
        ("evidence_missing", "ARTIFACT_NOT_FOUND"),
        ("evidence_corrupt", "ARTIFACT_HASH_MISMATCH"),
        ("signature_supplied", "MAPPING_REVIEW_INPUT_INVALID"),
        ("revision", "MAPPING_REVIEW_INPUT_INVALID"),
    ],
)
def test_cli_refuses_mismatched_inputs_without_publication(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: str, error_code: str
) -> None:
    paths = _inputs(tmp_path)
    statement = json.loads(paths["statement"].read_bytes())
    mapping = json.loads(paths["mapping"].read_bytes())
    argv = _argv(paths)
    if change == "mapping_digest":
        statement["mapping_digest"] = "f" * 64
    elif change == "mapping_id":
        statement["mapping_id"] = "other-mapping"
    elif change == "reviewer_mismatch":
        statement["reviewer_id"] = "different-reviewer"
    elif change == "review_time":
        statement["reviewed_at"] = "2026-01-03T00:00:00Z"
    elif change == "provisional":
        mapping["status"] = "provisional"
    elif change == "self_review":
        statement["author_id"] = statement["reviewer_id"]
    elif change == "untrusted":
        roots = json.loads(paths["trust-roots"].read_bytes())
        roots["mapping_reviewers"]["other-reviewer"] = roots["mapping_reviewers"].pop(
            "synthetic-reviewer"
        )
        _write_json(paths["trust-roots"], roots)
    elif change == "fixture":
        _write_json(paths["fixture"], {"private_provider_payload": "do not print"})
    elif change == "key":
        _write_key(
            paths["private-key"], Ed25519PrivateKey.from_private_bytes(b"w" * 32)
        )
    elif change == "invalid_key":
        paths["private-key"].write_text("private key contents must not be printed")
    elif change == "key_missing":
        paths["private-key"].unlink()
    elif change == "evidence_hash":
        statement["evidence_refs"][0]["content_hash"] = "f" * 64
    elif change == "evidence_media":
        statement["evidence_refs"][0]["media_type"] = "text/plain"
    elif change == "evidence_missing":
        statement["evidence_refs"][0]["artifact_id"] = "not-retained"
    elif change == "evidence_corrupt":
        next(paths["artifacts-root"].glob("*.artifact")).write_bytes(b"tampered")
    elif change == "signature_supplied":
        statement["signature"] = "0" * 128
    elif change == "revision":
        argv[-1] = "main"
    _write_json(paths["statement"], statement)
    _write_json(paths["mapping"], mapping)
    before = _file_inventory(tmp_path)
    assert main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"error_code": error_code}
    assert _file_inventory(tmp_path) == before
