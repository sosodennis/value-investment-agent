from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Annotated, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from .contracts import StrictModel
from .data_releases import ArtifactRefV1
from .fiscal_admission_history import FiscalHistoryHeadV1
from .history_recovery_contracts import FiscalIssuanceContextV1
from .replay import ArtifactPublicationV1
from .serialization import canonical_bytes, sha256_digest

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, Field(min_length=1, max_length=256)]
PrincipalKind = Literal["machine", "human"]
FiscalAuthorityRole = Literal[
    "source_preparer", "focus_validator", "classifier", "release_approver", "auditor"
]


class _AuthorityModel(StrictModel):
    model_config = ConfigDict(frozen=True)


class FiscalPublicIdentityV1(_AuthorityModel):
    principal_id: Identity
    principal_kind: PrincipalKind
    public_key_ed25519_base64: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def authentic_identity_shape(self) -> FiscalPublicIdentityV1:
        if not self.principal_id.startswith(self.principal_kind + ":"):
            raise ValueError("principal kind must match its qualified identity")
        try:
            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.public_key_ed25519_base64, validate=True)
            )
        except (ValueError, binascii.Error) as error:
            raise ValueError("authority requires an Ed25519 public key") from error
        return self

    @property
    def key_id(self) -> str:
        return hashlib.sha256(
            base64.b64decode(self.public_key_ed25519_base64, validate=True)
        ).hexdigest()


class FiscalRegistryRootIdentityV1(FiscalPublicIdentityV1):
    protocol: Literal["fundamental.fiscal-registry-root.v1"] = (
        "fundamental.fiscal-registry-root.v1"
    )
    root_id: Identity
    role: Literal["registry_administrator"] = "registry_administrator"
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def ordered_root_window(self) -> FiscalRegistryRootIdentityV1:
        if self.valid_until <= self.valid_from:
            raise ValueError("registry root validity must be ordered")
        return self


class FiscalConfiguredRegistryRootV1(_AuthorityModel):
    identity: FiscalRegistryRootIdentityV1
    evidence_ref: ArtifactRefV1


class FiscalAuthorityIdentityV1(FiscalPublicIdentityV1):
    protocol: Literal["fundamental.fiscal-authority-identity.v1"] = (
        "fundamental.fiscal-authority-identity.v1"
    )
    authority_id: Identity
    role: FiscalAuthorityRole


class FiscalConfiguredAuthorityV1(_AuthorityModel):
    identity: FiscalAuthorityIdentityV1
    provisioning_ref: ArtifactRefV1


class FiscalAuthorityDeploymentV1(_AuthorityModel):
    protocol: Literal["fundamental.fiscal-authority-deployment.v1"] = (
        "fundamental.fiscal-authority-deployment.v1"
    )
    roots: tuple[FiscalConfiguredRegistryRootV1, ...] = Field(
        min_length=1, max_length=32
    )
    authorities: tuple[FiscalConfiguredAuthorityV1, ...] = Field(max_length=256)

    @model_validator(mode="after")
    def independent_roster(self) -> FiscalAuthorityDeploymentV1:
        roots = tuple(root.identity for root in self.roots)
        identities = tuple(authority.identity for authority in self.authorities)
        if len({root.root_id for root in roots}) != len(roots):
            raise ValueError("registry root identities must be unique")
        if len({item.authority_id for item in identities}) != len(identities):
            raise ValueError("business authority identities must be unique")
        for index, identity in enumerate(identities):
            if any(
                identity.principal_id == root.principal_id
                or identity.key_id == root.key_id
                for root in roots
            ):
                raise ValueError("registry and business authority must be independent")
            for other in identities[index + 1 :]:
                if (
                    identity.key_id == other.key_id
                    and identity.principal_id != other.principal_id
                ):
                    raise ValueError(
                        "one authority key cannot represent different principals"
                    )
                if identity.role != other.role and (
                    identity.principal_id == other.principal_id
                    or identity.key_id == other.key_id
                ):
                    raise ValueError(
                        "distinct business roles require independent principals and keys"
                    )
        return self


class FiscalGrantAuthorityCommandV1(_AuthorityModel):
    kind: Literal["grant"] = "grant"
    command_id: Identity
    authority_id: Identity
    expires_at: AwareDatetime


class FiscalRevokeAuthorityCommandV1(_AuthorityModel):
    kind: Literal["revoke"] = "revoke"
    command_id: Identity
    authority_id: Identity
    grant_ref: ArtifactRefV1
    reason: str = Field(min_length=1, max_length=2048)


FiscalAuthorityCommandV1 = Annotated[
    FiscalGrantAuthorityCommandV1 | FiscalRevokeAuthorityCommandV1,
    Field(discriminator="kind"),
]


def fiscal_authority_command_digest(command: FiscalAuthorityCommandV1) -> str:
    return sha256_digest(command)


def fiscal_authority_command_artifact_id(command: FiscalAuthorityCommandV1) -> str:
    identity = {
        "authority_id": command.authority_id,
        "kind": command.kind,
        "command_id": command.command_id,
    }
    return "fiscal-authority-command-v1:" + sha256_digest(identity)


class FiscalRegistryOperatorV1(_AuthorityModel):
    root_id: Identity
    principal_id: Identity
    principal_kind: PrincipalKind
    key_id: Digest
    execution_ref: ArtifactRefV1


class FiscalRegistryExecutionV1(_AuthorityModel):
    protocol: Literal["fundamental.fiscal-registry-execution.v1"] = (
        "fundamental.fiscal-registry-execution.v1"
    )
    root_id: Identity
    principal_id: Identity
    principal_kind: PrincipalKind
    key_id: Digest
    execution_id: Identity
    operation: Literal["grant", "revoke"]
    command_digest: Digest
    issuance: FiscalIssuanceContextV1
    started_at: AwareDatetime


class FiscalAuthorityGrantV1(_AuthorityModel):
    kind: Literal["grant"] = "grant"
    protocol: Literal["fundamental.fiscal-authority-grant.v1"] = (
        "fundamental.fiscal-authority-grant.v1"
    )
    profile: Literal["fiscal-historical-statement-display-v1"] = (
        "fiscal-historical-statement-display-v1"
    )
    command: FiscalGrantAuthorityCommandV1
    identity: FiscalAuthorityIdentityV1
    provisioning_ref: ArtifactRefV1
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @model_validator(mode="after")
    def exact_grant(self) -> FiscalAuthorityGrantV1:
        if (
            self.command.authority_id != self.identity.authority_id
            or self.command.expires_at != self.valid_until
            or self.valid_until <= self.valid_from
        ):
            raise ValueError("authority grant differs from its command or validity")
        return self


class FiscalAuthorityRevocationV1(_AuthorityModel):
    kind: Literal["revoke"] = "revoke"
    protocol: Literal["fundamental.fiscal-authority-revocation.v1"] = (
        "fundamental.fiscal-authority-revocation.v1"
    )
    command: FiscalRevokeAuthorityCommandV1
    revoked_at: AwareDatetime


FiscalAuthorityRecordV1 = Annotated[
    FiscalAuthorityGrantV1 | FiscalAuthorityRevocationV1, Field(discriminator="kind")
]


class SignedFiscalAuthorityRecordV1(_AuthorityModel):
    protocol: Literal["fundamental.signed-fiscal-authority-record.v1"] = (
        "fundamental.signed-fiscal-authority-record.v1"
    )
    record: FiscalAuthorityRecordV1
    issuer: FiscalRegistryOperatorV1
    root_evidence_ref: ArtifactRefV1
    issuance: FiscalIssuanceContextV1
    signed_at: AwareDatetime
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def service_record_time(self) -> SignedFiscalAuthorityRecordV1:
        recorded = (
            self.record.valid_from
            if isinstance(self.record, FiscalAuthorityGrantV1)
            else self.record.revoked_at
        )
        if recorded != self.signed_at:
            raise ValueError(
                "authority effective time must equal its service signing time"
            )
        return self

    def signing_bytes(self) -> bytes:
        return canonical_bytes(self.model_dump(mode="json", exclude={"signature"}))

    @property
    def command_digest(self) -> str:
        return fiscal_authority_command_digest(self.record.command)

    @property
    def artifact_id(self) -> str:
        return fiscal_authority_command_artifact_id(self.record.command)


class CurrentFiscalAuthorityV1(_AuthorityModel):
    kind: Literal["current_authority"] = "current_authority"
    grant_ref: ArtifactRefV1
    grant: FiscalAuthorityGrantV1
    history_heads: tuple[FiscalHistoryHeadV1, ...]
    observed_at: AwareDatetime


class HistoricalFiscalAuthorityExplanationV1(_AuthorityModel):
    kind: Literal["historical_authority_explanation"] = (
        "historical_authority_explanation"
    )
    authority_id: Identity
    at: AwareDatetime
    state: Literal["active", "revoked", "expired", "not_yet_valid"]
    grant_ref: ArtifactRefV1
    grant: FiscalAuthorityGrantV1
    revocation_ref: ArtifactRefV1 | None
    history_heads: tuple[FiscalHistoryHeadV1, ...]


class FiscalAuthorityPublicationV1(_AuthorityModel):
    signed_record: SignedFiscalAuthorityRecordV1
    publication: ArtifactPublicationV1
    history_heads: tuple[FiscalHistoryHeadV1, ...]
