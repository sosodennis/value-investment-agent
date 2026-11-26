from __future__ import annotations

from collections.abc import Mapping
from typing import TypeAlias

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import TypeAdapter

from .data_releases import (
    ActiveDataReleaseV1,
    ActiveDataReleaseWithManifestV1,
    DataReleaseError,
    DataReleaseManifestV1,
    DataReleaseTrustRootsV1,
    DataReleaseVerificationV1,
    IssuerOperatingReleaseManifestV1,
    verify_data_release_candidate,
)
from .fiscal_release_contracts import (
    ActiveFiscalReleaseV1,
    FiscalReleaseManifestV1,
    FiscalReleaseVerificationV1,
    FiscalStoredVerificationV1,
)
from .serialization import canonical_bytes

PublicationManifest: TypeAlias = DataReleaseManifestV1 | FiscalReleaseManifestV1
PublicationVerification: TypeAlias = (
    DataReleaseVerificationV1 | FiscalStoredVerificationV1
)
ActivePublication: TypeAlias = ActiveDataReleaseWithManifestV1 | ActiveFiscalReleaseV1
_OBJECT = TypeAdapter(dict[str, object])


def decode_release_manifest(
    payload: Mapping[str, object] | bytes | str,
) -> PublicationManifest:
    raw = (
        payload.encode()
        if isinstance(payload, str)
        else payload
        if isinstance(payload, bytes)
        else canonical_bytes(payload)
    )
    fields = _OBJECT.validate_json(raw)
    tag = fields.get("protocol")
    if "protocol" not in fields:
        model: type[PublicationManifest] = DataReleaseManifestV1
    elif tag == "fundamental.issuer-operating-release.v1":
        model = IssuerOperatingReleaseManifestV1
    elif tag == "fundamental.fiscal-release-manifest.v1":
        model = FiscalReleaseManifestV1
    else:
        raise DataReleaseError(
            "DATA_RELEASE_PROTOCOL_UNSUPPORTED",
            "release manifest protocol is unsupported",
        )
    return model.model_validate_json(raw)


def decode_release_verification(
    payload: Mapping[str, object] | bytes | str,
) -> PublicationVerification:
    raw = (
        payload.encode()
        if isinstance(payload, str)
        else payload
        if isinstance(payload, bytes)
        else canonical_bytes(payload)
    )
    fields = _OBJECT.validate_json(raw)
    tag = fields.get("protocol")
    if "protocol" not in fields:
        return DataReleaseVerificationV1.model_validate_json(raw)
    if tag == "fundamental.fiscal-stored-verification.v1":
        return FiscalStoredVerificationV1.model_validate_json(raw)
    raise DataReleaseError(
        "DATA_RELEASE_PROTOCOL_UNSUPPORTED",
        "release verification protocol is unsupported",
    )


def require_publication_pair(
    manifest: PublicationManifest, verification: PublicationVerification
) -> None:
    if (
        isinstance(manifest, FiscalReleaseManifestV1)
        != isinstance(verification, FiscalStoredVerificationV1)
        or manifest.manifest_digest != verification.manifest_digest
    ):
        raise DataReleaseError(
            "DATA_RELEASE_VERIFICATION_MISMATCH",
            "release manifest and verification purpose or identity differ",
        )


def verify_fiscal_signature(
    verification: FiscalReleaseVerificationV1, roots: DataReleaseTrustRootsV1
) -> None:
    configured = roots.verifiers.get(verification.verifier_id)
    if configured is None or (
        configured.workflow_identity,
        configured.verification_suite_digest,
    ) != (verification.workflow_identity, verification.verification_suite_digest):
        raise DataReleaseError(
            "DATA_RELEASE_VERIFIER_MISMATCH",
            "fiscal verification workflow or suite differs from deployment",
        )
    checked = FiscalReleaseVerificationV1.model_validate_json(
        canonical_bytes(verification)
    )
    try:
        Ed25519PublicKey.from_public_bytes(configured.public_key()).verify(
            bytes.fromhex(checked.signature), checked.signing_bytes()
        )
    except (InvalidSignature, ValueError) as error:
        raise DataReleaseError(
            "DATA_RELEASE_VERIFICATION_SIGNATURE_INVALID",
            "fiscal verification signature is invalid",
        ) from error


def verify_publication_pair(
    manifest: PublicationManifest,
    verification: PublicationVerification,
    roots: DataReleaseTrustRootsV1,
) -> None:
    require_publication_pair(manifest, verification)
    if isinstance(manifest, FiscalReleaseManifestV1) and isinstance(
        verification, FiscalStoredVerificationV1
    ):
        verify_fiscal_signature(verification.signed, roots)
    elif isinstance(manifest, DataReleaseManifestV1) and isinstance(
        verification, DataReleaseVerificationV1
    ):
        verify_data_release_candidate(manifest, verification, roots)


def active_publication(
    active: ActiveDataReleaseV1, manifest: PublicationManifest
) -> ActivePublication:
    if isinstance(manifest, FiscalReleaseManifestV1):
        return ActiveFiscalReleaseV1(active=active, manifest=manifest)
    return ActiveDataReleaseWithManifestV1(active=active, manifest=manifest)
