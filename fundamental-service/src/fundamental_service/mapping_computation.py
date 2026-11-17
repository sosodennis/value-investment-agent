"""Computational mapping identity; exact signed input identity is unchanged."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from .serialization import canonical_bytes, sha256_digest
from .mapping_input_identity import MappingInputDigests
from .parser_action_contracts import Digest

if TYPE_CHECKING:
    from .automatic_mapping import AutomaticMappingRequestV1


class MappingComputationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["fundamental.mapping-computation.v1"] = (
        "fundamental.mapping-computation.v1"
    )
    policy_digest: Digest
    report_digest: Digest
    parameters: dict[str, JsonValue]


class MappingComputationIdentityV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    protocol: Literal["fundamental.mapping-computation-identity.v1"] = (
        "fundamental.mapping-computation-identity.v1"
    )
    digest: Digest


def mapping_computation(
    request: AutomaticMappingRequestV1,
    policy_digest: str,
    *,
    input_digests: MappingInputDigests | None = None,
) -> MappingComputationV1:
    """Name evaluated meaning; this fingerprint never authorizes any evidence.

    The separately signed exact input retains every source revision, raw action
    reference, issuer proof and execution coordinate. Only a full successful
    evaluation issues this nonauthorizing identity for approvals and abstentions.
    """
    fields = request.model_dump(
        mode="python", exclude={"original", "evidence_refs", "source_revision"}
    )
    original = request.original.model_dump(
        mode="python", exclude={"input_digest", "output_digest", "report"}
    )
    fields["original"] = original
    integrity = fields["integrity"]
    integrity["validation_evidence"] = tuple(
        v
        for v in integrity["validation_evidence"]
        if not v.startswith("sec-parser-action-")
    )
    parameters = json.loads(canonical_bytes(fields))
    identities = input_digests if input_digests is not None else MappingInputDigests()
    return MappingComputationV1(
        policy_digest=policy_digest,
        report_digest=identities.report_computation_digest(request.original.report),
        parameters=parameters,
    )


def mapping_computation_digest(
    request: AutomaticMappingRequestV1,
    policy_digest: str,
    *,
    input_digests: MappingInputDigests | None = None,
) -> str:
    return sha256_digest(
        mapping_computation(request, policy_digest, input_digests=input_digests)
    )
