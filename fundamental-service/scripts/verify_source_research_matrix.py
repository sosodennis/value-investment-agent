from __future__ import annotations

import html
import re
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, TypeAdapter

from fundamental_service.contracts import SecSourceRequestV1
from fundamental_service.free_source_policy import (
    default_macro_providers,
    default_reference_providers,
)
from fundamental_service.market_reference import ReferenceMetric
from fundamental_service.public_acquisition import PublicSourceAcquisition
from fundamental_service.public_source_catalog import (
    default_public_source_registrations,
)
from fundamental_service.quote_capture import quote_preparation_source_adapter
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.sec_source import sec_source_register
from fundamental_service.source_admission import SourceUsePolicyV1
from fundamental_service.source_capture import ReproducedMacroCaptureProfile
from fundamental_service.source_use_deployment import load_runtime_source_use_policy
from fundamental_service.terms_content import HtmlTermsScopeV1, terms_content_digest


class MatrixModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchUse(MatrixModel):
    status: Literal["evidence_supported", "refused", "unconfirmed"]
    reason: str


class Rights(MatrixModel):
    acquisition: ResearchUse
    storage: ResearchUse
    analysis: ResearchUse
    derived_display: ResearchUse
    raw_display: ResearchUse
    redistribution: ResearchUse


class ResearchRow(MatrixModel):
    row_id: str
    data_definition: str
    owner: Literal["sec", "macro", "reference", "quote", "research"]
    source_ids: tuple[str, ...]
    provider_id: str | None
    metric_ids: tuple[str, ...]
    source_profiles: tuple[str, ...]
    original_urls: tuple[str, ...]
    free_scope: str
    update_and_cost: str
    time_and_coverage: str
    rights: Rights
    evidence_refs: tuple[str, ...]
    downstream_impact: str


class ResearchEvidence(MatrixModel):
    evidence_id: str
    uri: str
    checked_on: date
    content_sha256: str | None
    boundary: str
    quote: str
    status: Literal["captured", "unconfirmed"]
    artifact_ref: str | None
    selected_content_sha256: str | None = None
    content_scope: HtmlTermsScopeV1 | None = None


class Matrix(MatrixModel):
    protocol: Literal["source-use-research-matrix-v1"]
    checked_on: date
    rows: tuple[ResearchRow, ...]
    evidence: tuple[ResearchEvidence, ...]


def _text(raw: bytes) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", raw.decode("utf-8"))).split())


def verify_evidence(
    evidence: ResearchEvidence,
    evidence_dir: Path,
    acquisitions: PublicSourceAcquisition,
) -> bytes | None:
    if evidence.status == "unconfirmed":
        if evidence.content_sha256 is not None or evidence.artifact_ref is not None:
            raise ValueError("unconfirmed research cannot claim a retained artifact")
        return None
    if not evidence.artifact_ref or not evidence.content_sha256 or not evidence.quote:
        raise ValueError("captured research requires original hash, quote and artifact")
    if evidence.artifact_ref.startswith("public-source-acquisition:"):
        receipt = acquisitions.read(evidence.artifact_ref)
        original = acquisitions.retained_source(receipt)
        if original.uri != evidence.uri:
            raise ValueError("matrix evidence URI differs from retained original")
        raw = original.content
    else:
        path = (evidence_dir / evidence.artifact_ref).resolve()
        if not path.is_relative_to(evidence_dir.resolve()):
            raise ValueError("matrix research artifact escapes evidence storage")
        raw = path.read_bytes()
    if sha256(raw).hexdigest() != evidence.content_sha256:
        raise ValueError(f"matrix research hash differs: {evidence.evidence_id}")
    if evidence.quote not in _text(raw):
        raise ValueError(
            f"matrix quotation absent from original: {evidence.evidence_id}"
        )
    if (
        evidence.content_scope is not None
        and terms_content_digest(raw, evidence.content_scope)
        != evidence.selected_content_sha256
    ):
        raise ValueError("matrix selected terms hash differs")
    return raw


def project_policy(
    row: ResearchRow, policy: SourceUsePolicyV1, originals: dict[str, bytes]
) -> dict[str, object]:
    rules = tuple(
        rule
        for rule in policy.rules
        if rule.provider_id == row.provider_id
        and rule.source_id in row.source_ids
        and rule.source_version in row.source_profiles
        and rule.metric_id in row.metric_ids
    )
    projections = []
    for rule in rules:
        terms = tuple(
            {
                "uri": requirement.uri,
                "expected_sha256": requirement.content_sha256,
                "content_scope": requirement.content_scope,
                "observed_sha256": terms_content_digest(
                    originals[requirement.uri], requirement.content_scope
                )
                if requirement.uri in originals
                else None,
                "matches": terms_content_digest(
                    originals[requirement.uri], requirement.content_scope
                )
                == requirement.content_sha256
                if requirement.uri in originals
                else None,
            }
            for requirement in rule.terms
        )
        projections.append(
            {
                "rule_id": rule.rule_id,
                "provider_id": rule.provider_id,
                "source_id": rule.source_id,
                "source_profile": rule.source_version,
                "metric_id": rule.metric_id,
                "permitted_uses": rule.permitted_uses,
                "required_notices": rule.required_notices,
                "terms": terms,
            }
        )
    supported = (
        row.rights.analysis.status == "evidence_supported"
        or row.rights.derived_display.status == "evidence_supported"
    )
    if row.rights.redistribution.status == "refused" and any(
        "raw_data_redistribution" in rule.permitted_uses for rule in rules
    ):
        raise ValueError(
            f"matrix redistribution refusal differs from installed policy: {row.row_id}"
        )
    if row.owner in {"macro", "reference"} and supported:
        if set(row.source_profiles) != {rule.source_version for rule in rules} or set(
            row.metric_ids
        ) != {rule.metric_id for rule in rules}:
            raise ValueError(
                f"matrix installed source profile or metric drifted: {row.row_id}"
            )
    if row.owner in {"macro", "reference"} and supported:
        if any(
            requirement.uri not in originals
            or terms_content_digest(
                originals[requirement.uri], requirement.content_scope
            )
            != requirement.content_sha256
            for rule in rules
            for requirement in rule.terms
        ):
            raise ValueError(
                f"matrix supported research differs from installed policy/evidence: {row.row_id}"
            )
        requested_uses = set()
        if row.rights.analysis.status == "evidence_supported":
            requested_uses.add("valuation_preparation")
        if row.rights.derived_display.status == "evidence_supported":
            requested_uses.add("derived_valuation_display")
        if any(not requested_uses <= set(rule.permitted_uses) for rule in rules):
            raise ValueError(f"matrix use differs from installed policy: {row.row_id}")
    return {
        "policy_version": policy.policy_version,
        "policy_digest": policy.digest,
        "rules": tuple(projections),
        "admission": "not_evaluated_without_source_reproduction",
    }


def verify_matrix(
    path: Path, evidence_dir: Path, acquisitions: PublicSourceAcquisition
) -> dict[str, object]:
    matrix = Matrix.model_validate_json(path.read_bytes())
    evidence = {item.evidence_id: item for item in matrix.evidence}
    if len(evidence) != len(matrix.evidence) or len(
        {row.row_id for row in matrix.rows}
    ) != len(matrix.rows):
        raise ValueError("matrix repeats row or evidence identities")
    originals = {
        item.evidence_id: raw
        for item in matrix.evidence
        if (raw := verify_evidence(item, evidence_dir, acquisitions)) is not None
    }
    policy = load_runtime_source_use_policy()
    registrations = default_public_source_registrations()
    public_ids = {item.spec.source_id for item in registrations}
    quote_adapter = quote_preparation_source_adapter(
        user_agent="Offline matrix verifier <offline@example.invalid>",
        policy=policy,
        api_key_file=None,
    )
    results = []
    for row in matrix.rows:
        if not set(row.evidence_refs) <= evidence.keys():
            raise ValueError(f"matrix evidence reference absent: {row.row_id}")
        row_originals = {
            evidence[ref].uri: originals[ref]
            for ref in row.evidence_refs
            if ref in originals
        }
        if any(
            getattr(row.rights, name).status == "evidence_supported"
            for name in Rights.model_fields
        ) and not any(evidence[ref].status == "captured" for ref in row.evidence_refs):
            raise ValueError(
                f"supported research lacks captured evidence: {row.row_id}"
            )
        if row.owner == "sec":
            for source_id in row.source_ids:
                sec_source_register().require(source_id)
            allowed = (
                SecSourceRequestV1.model_fields["source_selection_policy"].annotation,
                SecSourceRequestV1.model_fields["legal_use_profile"].annotation,
            )
            for profile in row.source_profiles:
                if not any(profile in get_args(annotation) for annotation in allowed):
                    raise ValueError(
                        "matrix SEC profile differs from owning request contract"
                    )
        elif row.owner in {"macro", "reference"}:
            if not set(row.source_ids) <= public_ids:
                raise ValueError(f"matrix source registration absent: {row.row_id}")
            capture_profiles = tuple(
                registration.profile
                for registration in registrations
                if registration.spec.source_id in row.source_ids
                and isinstance(registration.profile, ReproducedMacroCaptureProfile)
            )
            if capture_profiles:
                if (
                    set(row.source_profiles)
                    != {profile.source_version for profile in capture_profiles}
                    or set(row.metric_ids)
                    != {profile.series_id for profile in capture_profiles}
                    or {row.provider_id}
                    != {profile.provider.provider_id for profile in capture_profiles}
                ):
                    raise ValueError(
                        f"matrix capture registration drifted: {row.row_id}"
                    )
            else:
                known_profiles = {
                    rule.source_version
                    for rule in policy.rules
                    if rule.source_id in row.source_ids
                    and rule.provider_id == row.provider_id
                    and rule.metric_id in row.metric_ids
                }
                if not set(row.source_profiles) <= known_profiles:
                    raise ValueError(
                        f"matrix installed source profile drifted: {row.row_id}"
                    )
            for metric in row.metric_ids:
                if row.owner == "macro":
                    supported_metric = any(
                        provider.provider_id == row.provider_id
                        and provider.supports(metric)
                        for provider in default_macro_providers()
                    )
                else:
                    reference_metric = TypeAdapter(ReferenceMetric).validate_python(
                        metric
                    )
                    supported_metric = any(
                        provider.provider_id == row.provider_id
                        and provider.supports(reference_metric)
                        for provider in default_reference_providers()
                    )
                if not supported_metric:
                    raise ValueError(f"matrix provider/metric absent: {row.row_id}")
        elif row.owner == "quote":
            for source_id in row.source_ids:
                quote_adapter.source_register.require(source_id)
                if not all(
                    any(
                        provider.supports(source_id, profile)
                        for provider in default_quote_providers()
                    )
                    for profile in row.source_profiles
                ):
                    raise ValueError("matrix quote profile unsupported")
        results.append(
            {
                "row_id": row.row_id,
                "owner": row.owner,
                "registry": "research_only"
                if row.owner == "research"
                else "registered",
                "policy_projection": project_policy(row, policy, row_originals)
                if row.owner in {"macro", "reference", "quote"}
                else None,
            }
        )
    return {
        "matrix_sha256": sha256(path.read_bytes()).hexdigest(),
        "rows": tuple(results),
        "evidence_ids": tuple(evidence),
        "boundary": "Research statements and installed rules are separate. This projection does not grant source admission.",
    }
