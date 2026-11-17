"""Versioned identities for deterministic parser bodies, separate from delivery."""

from pathlib import PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    model_validator,
)

from .serialization import sha256_digest

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _ParserActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    representation: Literal["normalized", "archive"]
    entrypoint: str
    files: tuple[tuple[str, Digest], ...]
    normalization_inputs: tuple[Digest, ...]
    resources: tuple[tuple[str, Digest], ...]
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_version: str
    source_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_dependencies(self) -> Self:
        for collection in (self.files, self.resources):
            names = tuple(name for name, _ in collection)
            if names != tuple(sorted(set(names))):
                raise ValueError("parser dependency names must be unique and sorted")
        if (
            not self.files
            or any(
                PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
                for name, _ in self.files
            )
            or self.entrypoint not in dict(self.files)
        ):
            raise ValueError(
                "parser entrypoint and files must remain in the staged tree"
            )
        if self.normalization_inputs != tuple(sorted(set(self.normalization_inputs))):
            raise ValueError("normalization inputs must be unique and sorted")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class ParserActionInputV1(_ParserActionInput):
    protocol: Literal["sec-parser-action-input-v1"] = "sec-parser-action-input-v1"
    delivery_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    implementation_digest: Digest
    runtime_digest: Digest
    output_schema_digest: Digest


class ParserBuildIdentityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protocol: Literal["sec-parser-build-v1"] = "sec-parser-build-v1"
    implementation_digest: Digest
    runtime_digest: Digest
    output_schema_digest: Digest


class ParserActionInputV2(_ParserActionInput):
    protocol: Literal["sec-parser-action-input-v2"] = "sec-parser-action-input-v2"
    build: ParserBuildIdentityV1


ParserActionInput = ParserActionInputV1 | ParserActionInputV2


class ParserActionResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protocol: Literal["sec-parser-action-result-v1"] = "sec-parser-action-result-v1"
    request: ParserActionInputV1
    report_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def artifact_id(self) -> str:
        return (
            f"sec-parser-action-result-v1:{self.request.digest}:{sha256_digest(self)}"
        )

    def evidence_marker(self) -> str:
        return f"sec-parser-action-v1:{self.request.representation}:{self.request.digest}:{sha256_digest(self)}"


class ParserActionUseV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protocol: Literal["sec-parser-action-use-v1"] = "sec-parser-action-use-v1"
    action_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_artifact_id: str
    report_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    delivery_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    used_at: AwareDatetime
    reused: bool


class ParserActionResultV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protocol: Literal["sec-parser-action-result-v2"] = "sec-parser-action-result-v2"
    request: ParserActionInputV2
    report_content_hash: Digest

    @property
    def artifact_id(self) -> str:
        return (
            f"sec-parser-action-result-v2:{self.request.digest}:{sha256_digest(self)}"
        )

    def evidence_marker(self, delivery_digest: str) -> str:
        return f"sec-parser-action-v2:{self.request.representation}:{self.request.digest}:{sha256_digest(self)}:{delivery_digest}"


ParserActionResult = ParserActionResultV1 | ParserActionResultV2


class _ActionResultDocument(
    RootModel[
        Annotated[
            ParserActionResultV1 | ParserActionResultV2, Field(discriminator="protocol")
        ]
    ]
):
    pass


def read_action_result(raw: bytes) -> ParserActionResult:
    return _ActionResultDocument.model_validate_json(raw).root


class ParserActionUseV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protocol: Literal["sec-parser-action-use-v2"] = "sec-parser-action-use-v2"
    action_key: Digest
    result_artifact_id: str
    report_content_hash: Digest
    delivery_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    build: ParserBuildIdentityV1
    delivery_binding_digest: Digest
    used_at: AwareDatetime
    reused: bool


class ParserActionDeliveryV2(BaseModel):
    """Stable delivery binding; timestamped uses remain separate audit events."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protocol: Literal["sec-parser-action-delivery-v2"] = "sec-parser-action-delivery-v2"
    action_key: Digest
    result_artifact_id: str
    report_content_hash: Digest
    delivery_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    build: ParserBuildIdentityV1


def parser_action_markers(
    evidence: tuple[str, ...],
) -> tuple[tuple[str, str, str, str, str | None], ...]:
    """Decode only this protocol; malformed action claims fail closed."""
    values = []
    for marker in evidence:
        if not marker.startswith(("sec-parser-action-v1:", "sec-parser-action-v2:")):
            if marker.startswith("sec-parser-action-"):
                raise ValueError("unsupported parser action evidence version")
            continue
        parts = marker.split(":")
        if (
            len(parts) != (5 if parts[0] == "sec-parser-action-v2" else 4)
            or parts[1] not in {"normalized", "archive"}
            or any(
                len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
                for v in parts[2:]
            )
        ):
            raise ValueError("invalid parser action evidence marker")
        values.append(
            (
                parts[0][-2:],
                parts[1],
                parts[2],
                parts[3],
                parts[4] if len(parts) == 5 else None,
            )
        )
    if len({v[1] for v in values}) != len(values):
        raise ValueError("duplicate parser representation action")
    return tuple(sorted(values))
