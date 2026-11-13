"""Reproduce provider evidence and enforce a trusted, versioned source-use policy."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .macro_series import (
    MacroSeriesProviderPort,
    MacroSeriesVintageV1,
    reproduce_macro_vintage,
)
from .market_reference import (
    MarketReferenceProviderPort,
    MarketReferenceVintageV1,
    ReferenceMetric,
    reproduce_reference_vintage,
)
from .serialization import sha256_digest
from .snapshots import SnapshotError
from .source_evidence import RetainedSourceV1, SourceArtifactV1
from .terms_content import HtmlTermsScopeV1, TermsContentError, terms_content_digest

SourceUse = Literal[
    "valuation_preparation", "derived_valuation_display", "raw_data_redistribution"
]
SourceVintage = MacroSeriesVintageV1 | MarketReferenceVintageV1


class AdmissionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TermsRequirementV1(AdmissionModel):
    """Pin the whole document, or an explicit versioned exact content boundary."""

    uri: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_scope: HtmlTermsScopeV1 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class TermsContentCheckV1(AdmissionModel):
    uri: str
    raw_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_scope: HtmlTermsScopeV1
    selected_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceUseRuleV1(AdmissionModel):
    """Trusted deployment policy; request artifacts cannot install these rules."""

    rule_id: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    population: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    permitted_uses: tuple[SourceUse, ...] = Field(min_length=1)
    terms: tuple[TermsRequirementV1, ...] = Field(min_length=1)
    required_notices: tuple[str, ...] = Field(min_length=1)
    basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def unambiguous_terms(self) -> SourceUseRuleV1:
        if len({x.uri for x in self.terms}) != len(self.terms):
            raise ValueError("source-use rule repeats a terms URI")
        if len(set(self.permitted_uses)) != len(self.permitted_uses):
            raise ValueError("source-use rule repeats an intended use")
        return self


class SourceUsePolicyV1(AdmissionModel):
    """A code/configuration-owned catalog, independent of source adapters."""

    policy_version: str = Field(min_length=1)
    rules: tuple[SourceUseRuleV1, ...] = ()

    @model_validator(mode="after")
    def canonical_rules(self) -> SourceUsePolicyV1:
        if self.rules != tuple(sorted(self.rules, key=lambda x: x.rule_id)) or len(
            {x.rule_id for x in self.rules}
        ) != len(self.rules):
            raise ValueError("source-use rules must have distinct ordered identities")
        return self

    @property
    def digest(self) -> str:
        return sha256_digest(self)


class SourceUseCheckV1(AdmissionModel):
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_ids: tuple[str, ...]
    issue_codes: tuple[str, ...]
    required_notices: tuple[str, ...]
    terms_content_checks: tuple[TermsContentCheckV1, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )


class SourceAdmissionRequestV1(AdmissionModel):
    """A content-bound request, without expected numbers or permission flags."""

    kind: Literal["macro", "reference"]
    provider_id: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    intended_use: SourceUse
    valuation_at: datetime
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_artifacts: tuple[SourceArtifactV1, ...]
    terms_artifacts: tuple[SourceArtifactV1, ...]

    @model_validator(mode="after")
    def canonical_request(self) -> SourceAdmissionRequestV1:
        if self.valuation_at.tzinfo is None or self.valuation_at.utcoffset() is None:
            raise ValueError("source admission requires a valuation timezone")
        for items in (self.source_artifacts, self.terms_artifacts):
            if items != tuple(sorted(items, key=sha256_digest)):
                raise ValueError("source admission artifacts are not canonical")
        return self


class SourceAdmissionV1(AdmissionModel):
    """Source permission and availability, never issuer or financial-policy approval."""

    contract_version: Literal["fundamental.source-admission.v1"] = (
        "fundamental.source-admission.v1"
    )
    request: SourceAdmissionRequestV1
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    vintage: SourceVintage | None
    source_checks: tuple[SourceUseCheckV1, ...]
    status: Literal["admitted", "refused"]
    issue_codes: tuple[str, ...]
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_result(self) -> SourceAdmissionV1:
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("source admission issue codes are not canonical")
        if self.status != ("refused" if self.issue_codes else "admitted"):
            raise ValueError("source admission disposition differs from its issues")
        if self.vintage is None:
            if not self.issue_codes or self.source_checks:
                raise ValueError("unreproduced source must retain a refusal")
        else:
            if isinstance(self.vintage, MacroSeriesVintageV1):
                kind, metric = "macro", self.vintage.series_id
            else:
                kind, metric = "reference", self.vintage.metric
            if (
                self.request.kind != kind
                or self.vintage.provider_id != self.request.provider_id
                or metric != self.request.metric_id
                or tuple(sorted(self.vintage.artifacts, key=sha256_digest))
                != self.request.source_artifacts
                or tuple(x.artifact_digest for x in self.source_checks)
                != tuple(sha256_digest(x) for x in self.request.source_artifacts)
            ):
                raise ValueError("admission does not cover its reproduced originals")
            expected_codes = {
                code for check in self.source_checks for code in check.issue_codes
            }
            if self.vintage.available_at > self.request.valuation_at:
                expected_codes.add("SOURCE_NOT_AVAILABLE_AT_VALUATION")
            if self.issue_codes != tuple(sorted(expected_codes)):
                raise ValueError("source admission omits a retained refusal")
        if self.input_digest != sha256_digest(
            self.request
        ) or self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("source admission digest does not match content")
        return self


def _artifacts(sources: tuple[RetainedSourceV1, ...]) -> tuple[SourceArtifactV1, ...]:
    return tuple(
        sorted(
            (
                SourceArtifactV1(
                    source_id=x.source_id,
                    uri=x.uri,
                    source_version=x.source_version,
                    terms_reference=x.terms_reference,
                    captured_at=x.captured_at,
                    content_sha256=hashlib.sha256(x.content).hexdigest(),
                )
                for x in sources
            ),
            key=sha256_digest,
        )
    )


def _check_use(
    vintage: SourceVintage,
    artifact: SourceArtifactV1,
    *,
    intended_use: SourceUse,
    terms: tuple[RetainedSourceV1, ...],
    policy: SourceUsePolicyV1,
) -> SourceUseCheckV1:
    metric = (
        vintage.series_id
        if isinstance(vintage, MacroSeriesVintageV1)
        else vintage.metric
    )
    population = (
        vintage.series_id
        if isinstance(vintage, MacroSeriesVintageV1)
        else vintage.population
    )
    rules = tuple(
        x
        for x in policy.rules
        if (
            x.provider_id == vintage.provider_id
            and x.metric_id == metric
            and x.population == population
            and x.source_id == artifact.source_id
            and x.source_version == artifact.source_version
            and x.terms_reference == artifact.terms_reference
        )
    )
    codes: set[str] = set()
    notices: tuple[str, ...] = ()
    terms_checks: list[TermsContentCheckV1] = []
    if not rules:
        codes.add("SOURCE_USE_POLICY_MISSING")
    elif len(rules) != 1:
        codes.add("SOURCE_USE_POLICY_AMBIGUOUS")
    else:
        rule = rules[0]
        notices = rule.required_notices
        if intended_use not in rule.permitted_uses:
            codes.add("SOURCE_USE_PURPOSE_UNSUPPORTED")
        for requirement in rule.terms:
            matches = {
                hashlib.sha256(x.content).hexdigest(): x
                for x in terms
                if x.uri == requirement.uri
            }
            if not matches:
                codes.add("SOURCE_USE_TERMS_MISSING")
            elif len(matches) != 1:
                codes.add("SOURCE_USE_TERMS_AMBIGUOUS")
            else:
                raw_digest, source = next(iter(matches.items()))
                try:
                    selected_digest = terms_content_digest(
                        source.content, requirement.content_scope
                    )
                except TermsContentError:
                    codes.add("SOURCE_USE_TERMS_SCOPE_INVALID")
                    continue
                if requirement.content_scope is not None:
                    terms_checks.append(
                        TermsContentCheckV1(
                            uri=requirement.uri,
                            raw_content_sha256=raw_digest,
                            content_scope=requirement.content_scope,
                            selected_content_sha256=selected_digest,
                        )
                    )
                if selected_digest != requirement.content_sha256:
                    codes.add("SOURCE_USE_TERMS_CHANGED")
    return SourceUseCheckV1(
        artifact_digest=sha256_digest(artifact),
        rule_ids=tuple(x.rule_id for x in rules),
        issue_codes=tuple(sorted(codes)),
        required_notices=notices,
        terms_content_checks=tuple(sorted(terms_checks, key=sha256_digest)),
    )


def _admit(
    *,
    kind: Literal["macro", "reference"],
    provider_id: str,
    reproduce: Callable[[], SourceVintage],
    metric_id: str,
    sources: tuple[RetainedSourceV1, ...],
    terms: tuple[RetainedSourceV1, ...],
    policy: SourceUsePolicyV1,
    valuation_at: datetime,
    intended_use: SourceUse,
    expected: SourceAdmissionV1 | None,
) -> SourceAdmissionV1:
    request = SourceAdmissionRequestV1(
        kind=kind,
        provider_id=provider_id,
        metric_id=metric_id,
        intended_use=intended_use,
        valuation_at=valuation_at,
        policy_version=policy.policy_version,
        policy_digest=policy.digest,
        source_artifacts=_artifacts(sources),
        terms_artifacts=_artifacts(terms),
    )
    codes: set[str] = set()
    vintage: SourceVintage | None = None
    checks: tuple[SourceUseCheckV1, ...] = ()
    try:
        vintage = reproduce()
    except (ValueError, SnapshotError) as error:
        codes.add("SOURCE_REPRODUCTION_FAILED")
        if isinstance(error, SnapshotError):
            codes.add(error.code)
    if vintage is not None:
        checks = tuple(
            _check_use(
                vintage,
                artifact,
                intended_use=intended_use,
                terms=terms,
                policy=policy,
            )
            for artifact in request.source_artifacts
        )
        codes.update(code for check in checks for code in check.issue_codes)
        if vintage.available_at > valuation_at:
            codes.add("SOURCE_NOT_AVAILABLE_AT_VALUATION")
    payload = {
        "contract_version": "fundamental.source-admission.v1",
        "request": request,
        "input_digest": sha256_digest(request),
        "vintage": vintage,
        "source_checks": checks,
        "issue_codes": tuple(sorted(codes)),
        "status": "refused" if codes else "admitted",
    }
    result = SourceAdmissionV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )
    if expected is not None and result != expected:
        raise SnapshotError(
            "SOURCE_ADMISSION_REPLAY_MISMATCH",
            "source admission differs from reproduced evidence",
        )
    return result


def admit_macro_source(
    provider: MacroSeriesProviderPort,
    *,
    series_id: str,
    sources: tuple[RetainedSourceV1, ...],
    terms: tuple[RetainedSourceV1, ...],
    policy: SourceUsePolicyV1,
    valuation_at: datetime,
    intended_use: SourceUse = "valuation_preparation",
    expected: SourceAdmissionV1 | None = None,
) -> SourceAdmissionV1:
    return _admit(
        kind="macro",
        provider_id=provider.provider_id,
        reproduce=lambda: reproduce_macro_vintage(
            provider, series_id=series_id, sources=sources
        ),
        metric_id=series_id,
        sources=sources,
        terms=terms,
        policy=policy,
        valuation_at=valuation_at,
        intended_use=intended_use,
        expected=expected,
    )


def admit_reference_source(
    provider: MarketReferenceProviderPort,
    *,
    metric: ReferenceMetric,
    sources: tuple[RetainedSourceV1, ...],
    terms: tuple[RetainedSourceV1, ...],
    policy: SourceUsePolicyV1,
    valuation_at: datetime,
    intended_use: SourceUse = "valuation_preparation",
    expected: SourceAdmissionV1 | None = None,
) -> SourceAdmissionV1:
    return _admit(
        kind="reference",
        provider_id=provider.provider_id,
        reproduce=lambda: reproduce_reference_vintage(
            provider, metric=metric, sources=sources
        ),
        metric_id=metric,
        sources=sources,
        terms=terms,
        policy=policy,
        valuation_at=valuation_at,
        intended_use=intended_use,
        expected=expected,
    )
