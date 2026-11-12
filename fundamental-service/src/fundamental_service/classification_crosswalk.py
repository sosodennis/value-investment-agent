"""Versioned, provider-neutral issuer-classification crosswalks."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .issuer_classification import IssuerClassificationEvidenceV1
from .serialization import sha256_digest
from .snapshots import SnapshotError


class CrosswalkModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClassificationCrosswalkPolicyV1(CrosswalkModel):
    """The exact source scheme and destination taxonomy selected by policy."""

    provider_id: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    mapping_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_scheme: str = Field(min_length=1)
    target_taxonomy: str = Field(min_length=1)


class IndustryCrosswalkRuleV1(CrosswalkModel):
    """One exact classification code to one published reference subject."""

    rule_id: str = Field(min_length=1)
    source_scheme: str = Field(min_length=1)
    source_code: str = Field(pattern=r"^[0-9]{4}$")
    target_taxonomy: str = Field(min_length=1)
    target_population: str = Field(min_length=1)
    target_subject: str = Field(min_length=1)
    target_subject_kind: Literal["industry"] = "industry"
    basis: str = Field(min_length=1)


class ClassificationCrosswalkProviderPort(Protocol):
    """Map classifications without I/O, policy selection, or valuation math."""

    provider_id: str
    mapping_version: str
    target_taxonomy: str

    @property
    def mapping_digest(self) -> str: ...

    def candidates(
        self, *, source_scheme: str, source_code: str, target_taxonomy: str
    ) -> tuple[IndustryCrosswalkRuleV1, ...]: ...


class IndustryCrosswalkEvidenceV1(CrosswalkModel):
    """Reproducible mapping or retained refusal for one issuer/original."""

    protocol: Literal["industry-crosswalk-v1"] = "industry-crosswalk-v1"
    issuer_id: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    report_period_end: date
    valuation_at: datetime
    classification_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_scheme: str | None
    source_code: str | None
    source_value: str | None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    provider_id: str = Field(min_length=1)
    mapping_version: str = Field(min_length=1)
    mapping_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_taxonomy: str = Field(min_length=1)
    candidate_rule_ids: tuple[str, ...]
    rule_id: str | None
    rule_basis: str | None
    target_population: str | None
    target_subject: str | None
    target_subject_kind: Literal["industry"] | None
    status: Literal["mapped", "refused"]
    issue_codes: tuple[str, ...]
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def canonical_result(self) -> IndustryCrosswalkEvidenceV1:
        if self.valuation_at.tzinfo is None or self.valuation_at.utcoffset() is None:
            raise ValueError("crosswalk valuation time requires a timezone")
        if self.candidate_rule_ids != tuple(sorted(set(self.candidate_rule_ids))):
            raise ValueError("crosswalk candidate rule identities are not canonical")
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("crosswalk issue codes are not canonical")
        mapped = self.status == "mapped"
        if mapped != (not self.issue_codes):
            raise ValueError("crosswalk status differs from its issue codes")
        if mapped:
            if (
                self.rule_id is None
                or self.rule_basis is None
                or self.candidate_rule_ids != (self.rule_id,)
                or self.target_population is None
                or self.target_subject is None
                or self.target_subject_kind != "industry"
                or self.source_scheme is None
                or self.source_code is None
                or self.source_value is None
                or self.source_sha256 is None
            ):
                raise ValueError("mapped crosswalk requires complete source and target")
        elif any(
            value is not None
            for value in (
                self.rule_id,
                self.rule_basis,
                self.target_population,
                self.target_subject,
                self.target_subject_kind,
            )
        ):
            raise ValueError("refused crosswalk cannot provide a target")
        if self.input_digest != sha256_digest(
            {
                "classification_digest": self.classification_digest,
                "policy_digest": self.policy_digest,
                "provider_id": self.provider_id,
                "mapping_version": self.mapping_version,
                "mapping_digest": self.mapping_digest,
            }
        ):
            raise ValueError("crosswalk input digest does not match its pins")
        if self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("crosswalk output digest does not match content")
        return self


def apply_industry_crosswalk(
    classification: IssuerClassificationEvidenceV1,
    *,
    policy: ClassificationCrosswalkPolicyV1,
    provider: ClassificationCrosswalkProviderPort,
    expected: IndustryCrosswalkEvidenceV1 | None = None,
) -> IndustryCrosswalkEvidenceV1:
    """Apply one pinned crosswalk and preserve source, mapping and refusal evidence."""
    classification = IssuerClassificationEvidenceV1.model_validate_json(
        classification.model_dump_json()
    )
    policy = ClassificationCrosswalkPolicyV1.model_validate_json(
        policy.model_dump_json()
    )
    observation = classification.observation
    attributes = (
        tuple(x for x in observation.attributes if x.role == "industry_code")
        if observation is not None
        else ()
    )
    attribute = attributes[0] if len(attributes) == 1 else None
    scheme = attribute.scheme if attribute is not None else None
    code = attribute.value if attribute is not None else None
    mapping_digest = provider.mapping_digest
    policy_digest = sha256_digest(policy)
    input_digest = sha256_digest(
        {
            "classification_digest": classification.output_digest,
            "policy_digest": policy_digest,
            "provider_id": provider.provider_id,
            "mapping_version": provider.mapping_version,
            "mapping_digest": mapping_digest,
        }
    )
    rules: tuple[IndustryCrosswalkRuleV1, ...] = ()
    codes = set(classification.issue_codes)
    if classification.status != "matched" or observation is None:
        codes.add("ISSUER_CLASSIFICATION_NOT_MATCHED")
    elif observation.available_at > classification.request.valuation_at:
        codes.add("ISSUER_CLASSIFICATION_NOT_AVAILABLE")
    if attribute is None:
        codes.add("ISSUER_CLASSIFICATION_INDUSTRY_MISSING")
    if (
        provider.provider_id != policy.provider_id
        or provider.mapping_version != policy.mapping_version
        or mapping_digest != policy.mapping_digest
        or provider.target_taxonomy != policy.target_taxonomy
    ):
        codes.add("ISSUER_CLASSIFICATION_CROSSWALK_PROVIDER_MISMATCH")
    if attribute is not None:
        if scheme != policy.source_scheme:
            codes.add("ISSUER_CLASSIFICATION_CROSSWALK_SCHEME_UNSUPPORTED")
        elif re.fullmatch(r"[0-9]{4}", code or "") is None:
            codes.add("ISSUER_CLASSIFICATION_CROSSWALK_CODE_INVALID")
        elif not codes:
            try:
                rules = tuple(
                    IndustryCrosswalkRuleV1.model_validate_json(item.model_dump_json())
                    for item in provider.candidates(
                        source_scheme=scheme,
                        source_code=code or "",
                        target_taxonomy=policy.target_taxonomy,
                    )
                )
            except (TypeError, ValueError):
                codes.add("ISSUER_CLASSIFICATION_CROSSWALK_REPRODUCTION_FAILED")
            if any(
                rule.source_scheme != scheme
                or rule.source_code != code
                or rule.target_taxonomy != policy.target_taxonomy
                for rule in rules
            ):
                codes.add("ISSUER_CLASSIFICATION_CROSSWALK_PROVIDER_MISMATCH")
            elif len(rules) == 0:
                codes.add("ISSUER_CLASSIFICATION_CROSSWALK_UNMAPPED")
            elif len(rules) > 1:
                codes.add("ISSUER_CLASSIFICATION_CROSSWALK_AMBIGUOUS")

    rule = rules[0] if len(rules) == 1 and not codes else None
    issue_codes = tuple(sorted(codes))
    payload = {
        "protocol": "industry-crosswalk-v1",
        "issuer_id": classification.request.issuer_id,
        "accession_number": classification.request.accession_number,
        "report_period_end": classification.request.report_period_end,
        "valuation_at": classification.request.valuation_at,
        "classification_digest": classification.output_digest,
        "policy_digest": policy_digest,
        "source_scheme": scheme,
        "source_code": code,
        "source_value": attribute.source_value if attribute else None,
        "source_sha256": attribute.source_sha256 if attribute else None,
        "provider_id": provider.provider_id,
        "mapping_version": provider.mapping_version,
        "mapping_digest": mapping_digest,
        "target_taxonomy": policy.target_taxonomy,
        "candidate_rule_ids": tuple(sorted(item.rule_id for item in rules)),
        "rule_id": rule.rule_id if rule else None,
        "rule_basis": rule.basis if rule else None,
        "target_population": rule.target_population if rule else None,
        "target_subject": rule.target_subject if rule else None,
        "target_subject_kind": rule.target_subject_kind if rule else None,
        "status": "mapped" if rule else "refused",
        "issue_codes": issue_codes,
        "input_digest": input_digest,
    }
    result = IndustryCrosswalkEvidenceV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )
    if expected is not None and expected != result:
        raise SnapshotError(
            "ISSUER_CLASSIFICATION_CROSSWALK_REPLAY_MISMATCH",
            "issuer classification crosswalk differs from the retained replay",
        )
    return result
