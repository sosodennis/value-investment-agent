import base64
import os
import socket
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from fundamental_service.fiscal_focus_witness import (
    FiscalFocusValidatorAuthorityV1,
    configured_focus_authority,
    configured_focus_private_key,
    load_validator_authority,
    load_validator_private_key,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError


def authority(key: ed25519.Ed25519PrivateKey) -> FiscalFocusValidatorAuthorityV1:
    return FiscalFocusValidatorAuthorityV1(
        authority_id="synthetic-configured-validator",
        principal_id="synthetic-machine-principal",
        public_key_ed25519_base64=base64.b64encode(
            key.public_key().public_bytes_raw()
        ).decode(),
        valid_until=datetime.now(UTC) + timedelta(days=1),
    )


def test_loads_configured_authority_and_private_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = ed25519.Ed25519PrivateKey.generate()
    record = authority(key)
    authority_path = tmp_path / "authority.json"
    authority_path.write_bytes(canonical_bytes(record))
    key_path = tmp_path / "private.pem"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    monkeypatch.setenv("FUNDAMENTAL_FISCAL_FOCUS_AUTHORITY_FILE", str(authority_path))
    monkeypatch.setenv("FUNDAMENTAL_FISCAL_FOCUS_PRIVATE_KEY_FILE", str(key_path))
    assert configured_focus_authority() == record
    assert configured_focus_private_key().private_bytes_raw() == key.private_bytes_raw()
    revoked = record.model_copy(update={"status": "revoked"})
    authority_path.write_bytes(canonical_bytes(revoked))
    assert configured_focus_authority() == revoked


@pytest.mark.parametrize(
    "name,loader",
    [
        ("FUNDAMENTAL_FISCAL_FOCUS_AUTHORITY_FILE", configured_focus_authority),
        ("FUNDAMENTAL_FISCAL_FOCUS_PRIVATE_KEY_FILE", configured_focus_private_key),
    ],
)
def test_missing_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch, name, loader
) -> None:
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(SnapshotError) as failure:
        loader()
    assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_UNCONFIGURED"


@pytest.mark.parametrize(
    "loader", [load_validator_authority, load_validator_private_key]
)
@pytest.mark.parametrize(
    "kind", ["missing", "directory", "symlink", "fifo", "socket", "oversized"]
)
def test_configuration_rejects_non_regular_and_oversized_files(
    tmp_path: Path, loader, kind: str
) -> None:
    with ExitStack() as cleanup:
        path = tmp_path / "configuration"
        key = ed25519.Ed25519PrivateKey.generate()
        valid_bytes = (
            canonical_bytes(authority(key))
            if loader is load_validator_authority
            else key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        if kind == "directory":
            path.mkdir()
        elif kind == "symlink":
            target = tmp_path / "target"
            target.write_bytes(valid_bytes)
            target.chmod(0o600)
            path.symlink_to(target)
        elif kind == "fifo":
            os.mkfifo(path, 0o600)
        elif kind == "socket":
            root = cleanup.enter_context(TemporaryDirectory(dir="/tmp"))
            path = Path(root) / "socket"
            listener = cleanup.enter_context(socket.socket(socket.AF_UNIX))
            listener.bind(str(path))
        elif kind == "oversized":
            path.write_bytes(valid_bytes + b"\n" * 16_385)
            path.chmod(0o600)
        with pytest.raises(SnapshotError) as failure:
            loader(path)
        assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_INVALID"


def test_private_key_rejects_shared_permissions(tmp_path: Path) -> None:
    path = tmp_path / "private.pem"
    path.write_bytes(
        ed25519.Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o640)
    with pytest.raises(SnapshotError) as failure:
        load_validator_private_key(path)
    assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_INVALID"


def test_authority_rejects_a_different_role(tmp_path: Path) -> None:
    record = authority(ed25519.Ed25519PrivateKey.generate())
    path = tmp_path / "authority.json"
    path.write_bytes(
        canonical_bytes(record.model_dump(mode="json") | {"role": "mapping-reviewer"})
    )
    with pytest.raises(SnapshotError) as failure:
        load_validator_authority(path)
    assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_INVALID"


@pytest.mark.parametrize("raw", [b"malformed", b"{}", b'{"role":"mapping-reviewer"}'])
def test_authority_rejects_malformed_or_incomplete_json(
    tmp_path: Path, raw: bytes
) -> None:
    path = tmp_path / "authority.json"
    path.write_bytes(raw)
    with pytest.raises(SnapshotError) as failure:
        load_validator_authority(path)
    assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_INVALID"


@pytest.mark.parametrize("kind", ["malformed", "wrong-type"])
def test_private_key_rejects_malformed_and_wrong_key_type(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "private.pem"
    path.write_bytes(
        b"synthetic"
        if kind == "malformed"
        else ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    with pytest.raises(SnapshotError) as failure:
        load_validator_private_key(path)
    assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_INVALID"
