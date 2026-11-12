"""Select issuer/date reference rows from admitted, interchangeable sources.

Selection does not approve issuer classification or a complete financial policy.
Industry unlevered beta and country tax retain their published meanings.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import MarketPolicyEvidenceV1, TraceV1
from .market_reference import (
    MarketReferenceVintageV1,
    ReferenceMetric,
    ReferenceRowV1,
    select_reference_vintage,
)
from .serialization import sha256_digest
from .source_admission import SourceAdmissionV1


class ReferenceSelectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MarketReferenceSelectionError(ValueError):
    """A source-selection result cannot authorize a market-policy role."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MarketReferenceSelectionPolicyV1(ReferenceSelectionModel):
    """Exact selection intent, without provider names or classification authority."""

    policy_version: str = Field(min_length=1)
    metric: ReferenceMetric
    population: str = Field(min_length=1)
    subject_kind: Literal["country", "industry"]
    subject: str = Field(min_length=1)
    maximum_age_days: int = Field(ge=0)

    @model_validator(mode="after")
    def exact_subject(self) -> "MarketReferenceSelectionPolicyV1":
        expected = "industry" if self.metric.startswith("industry.") else "country"
        if self.subject_kind != expected or self.subject != self.subject.strip():
            raise ValueError(
                "reference selection requires an exact metric/subject kind"
            )
        return self


class MarketReferenceSelectionV1(ReferenceSelectionModel):
    """A selected original row or its retained source-selection refusal."""

    policy: MarketReferenceSelectionPolicyV1
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["selected", "refused"]
    issue_codes: tuple[str, ...]
    vintage_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    row: ReferenceRowV1 | None = None
    trace: TraceV1 | None = None
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def value(self) -> Decimal | None:
        return self.row.value if self.status == "selected" and self.row else None

    @model_validator(mode="after")
    def selection_matches_content(self) -> "MarketReferenceSelectionV1":
        if self.issue_codes != tuple(sorted(set(self.issue_codes))):
            raise ValueError("reference selection issues are not canonical")
        if self.status == "selected":
            if (
                self.issue_codes
                or self.row is None
                or self.row.value is None
                or self.trace is None
                or self.vintage_digest is None
            ):
                raise ValueError("selected reference requires a complete original row")
        elif not self.issue_codes or self.trace is not None:
            raise ValueError(
                "refused reference requires issues and cannot supply a trace"
            )
        if self.row is not None and (
            self.vintage_digest is None
            or self.row.subject != self.policy.subject
            or self.row.subject_kind != self.policy.subject_kind
        ):
            raise ValueError(
                "retained reference row differs from the requested subject"
            )
        if self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("reference selection digest does not match content")
        return self


class IssuerMarketReferencePlanV1(ReferenceSelectionModel):
    """Bind explicit row requests to one issuer and point in time."""

    protocol: Literal["issuer-market-reference-selection-v1"] = (
        "issuer-market-reference-selection-v1"
    )
    issuer_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    valuation_at: datetime
    selections: tuple[MarketReferenceSelectionPolicyV1, ...] = Field(min_length=1)

    @field_validator("valuation_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reference selection requires a valuation timezone")
        return value.astimezone(UTC)

    @field_validator("selections")
    @classmethod
    def ordered_selections(
        cls, value: tuple[MarketReferenceSelectionPolicyV1, ...]
    ) -> tuple[MarketReferenceSelectionPolicyV1, ...]:
        if len({x.metric for x in value}) != len(value):
            raise ValueError("issuer reference plan repeats a metric")
        return tuple(sorted(value, key=lambda x: x.metric))


class IssuerMarketReferenceSelectionV1(ReferenceSelectionModel):
    """Retain every requested metric, including partial or wholly refused joins."""

    plan: IssuerMarketReferencePlanV1
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selections: tuple[MarketReferenceSelectionV1, ...]
    status: Literal["selected", "partial", "refused"]
    issue_codes: tuple[str, ...]
    output_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete_accounting(self) -> "IssuerMarketReferenceSelectionV1":
        if tuple(x.policy for x in self.selections) != self.plan.selections:
            raise ValueError("issuer reference result omits or substitutes a request")
        selected = sum(x.status == "selected" for x in self.selections)
        expected = (
            "selected"
            if selected == len(self.selections)
            else "partial"
            if selected
            else "refused"
        )
        issues = tuple(
            sorted({code for x in self.selections for code in x.issue_codes})
        )
        if self.status != expected or self.issue_codes != issues:
            raise ValueError("issuer reference disposition omits a retained refusal")
        if self.output_digest != sha256_digest(
            self.model_dump(exclude={"output_digest"})
        ):
            raise ValueError("issuer reference digest does not match content")
        return self


def _ordered_admissions(
    admissions: tuple[SourceAdmissionV1, ...],
) -> tuple[SourceAdmissionV1, ...]:
    return tuple(
        sorted(
            {x.output_digest: x for x in admissions}.values(),
            key=lambda x: x.output_digest,
        )
    )


def select_market_reference(
    admissions: tuple[SourceAdmissionV1, ...],
    *,
    policy: MarketReferenceSelectionPolicyV1,
    valuation_at: datetime,
) -> MarketReferenceSelectionV1:
    """Select latest eligible vintage first; never fill a missing row from the past.

    The trusted release loader must reproduce admissions before calling this
    pure selector. A selection plan itself supplies no source-use permission.
    """
    if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
        raise ValueError("reference selection requires a valuation timezone")
    valuation_at = valuation_at.astimezone(UTC)
    ordered = _ordered_admissions(admissions)
    input_digest = sha256_digest(
        {"policy": policy, "valuation_at": valuation_at, "admissions": ordered}
    )
    vintage: MarketReferenceVintageV1 | None = None
    row: ReferenceRowV1 | None = None

    def result(
        code: str | None = None, trace: TraceV1 | None = None
    ) -> MarketReferenceSelectionV1:
        payload = {
            "policy": policy,
            "input_digest": input_digest,
            "status": "refused" if code else "selected",
            "issue_codes": (code,) if code else (),
            "vintage_digest": vintage.content_digest if vintage else None,
            "row": row,
            "trace": trace,
        }
        return MarketReferenceSelectionV1.model_validate(
            {**payload, "output_digest": sha256_digest(payload)}
        )

    eligible = tuple(
        x
        for x in ordered
        if x.status == "admitted"
        and x.request.intended_use == "valuation_preparation"
        and isinstance(x.vintage, MarketReferenceVintageV1)
        and x.vintage.metric == policy.metric
        and x.vintage.population == policy.population
        and x.vintage.available_at <= valuation_at
    )
    if not eligible:
        return result("MARKET_REFERENCE_SOURCE_UNAVAILABLE")
    try:
        vintage = select_reference_vintage(
            tuple(
                x.vintage
                for x in eligible
                if isinstance(x.vintage, MarketReferenceVintageV1)
            ),
            metric=policy.metric,
            population=policy.population,
            valuation_at=valuation_at,
        )
    except ValueError:
        return result("MARKET_REFERENCE_SOURCE_AMBIGUOUS")
    matches = tuple(x for x in eligible if x.vintage == vintage)
    if len(matches) != 1:
        return result("MARKET_REFERENCE_ADMISSION_AMBIGUOUS")
    if (valuation_at.date() - vintage.source_updated_on).days > policy.maximum_age_days:
        return result("MARKET_REFERENCE_SOURCE_STALE")
    row = next(
        (
            x
            for x in vintage.rows
            if x.subject == policy.subject and x.subject_kind == policy.subject_kind
        ),
        None,
    )
    if row is None:
        return result("MARKET_REFERENCE_SUBJECT_UNAVAILABLE")
    if row.value is None:
        return result("MARKET_REFERENCE_VALUE_MISSING")
    originals = tuple(
        x for x in vintage.artifacts if x.content_sha256 == row.source_sha256
    )
    if len(originals) != 1:
        return result("MARKET_REFERENCE_ORIGINAL_AMBIGUOUS")
    original = originals[0]
    trace = TraceV1(
        source_refs=(
            original.content_sha256,
            matches[0].output_digest,
            vintage.content_digest,
            sha256_digest(row),
            input_digest,
        ),
        source_ids=(original.source_id,),
        source_uris=(original.uri,),
        source_versions=(original.source_version, policy.policy_version),
        terms_references=(original.terms_reference,),
        as_of=datetime.combine(vintage.source_updated_on, datetime.min.time(), UTC),
        available_at=vintage.available_at,
        captured_at=vintage.captured_at,
        description=f"Published {policy.metric} for exact {policy.subject_kind} row {policy.subject}; issuer classification is a separate policy gate",
    )
    return result(trace=trace)


def select_issuer_market_references(
    plan: IssuerMarketReferencePlanV1,
    *,
    admissions: tuple[SourceAdmissionV1, ...],
) -> IssuerMarketReferenceSelectionV1:
    """Join every issuer/date request without promoting partial source evidence."""
    ordered = _ordered_admissions(admissions)
    selections = tuple(
        select_market_reference(ordered, policy=policy, valuation_at=plan.valuation_at)
        for policy in plan.selections
    )
    selected = sum(x.status == "selected" for x in selections)
    payload = {
        "plan": plan,
        "input_digest": sha256_digest({"plan": plan, "admissions": ordered}),
        "selections": selections,
        "status": "selected"
        if selected == len(selections)
        else "partial"
        if selected
        else "refused",
        "issue_codes": tuple(
            sorted({code for x in selections for code in x.issue_codes})
        ),
    }
    return IssuerMarketReferenceSelectionV1.model_validate(
        {**payload, "output_digest": sha256_digest(payload)}
    )


def verify_market_reference_policy_evidence(
    evidence_items: tuple[MarketPolicyEvidenceV1, ...],
    *,
    selections: tuple[MarketReferenceSelectionV1, ...],
) -> dict[str, TraceV1]:
    """Bind supported observed roles to an exact selected reference row.

    Country ERP is a usable reference input. An industry *unlevered* beta is
    deliberately rejected for the ``beta`` role: relevering to an issuer beta
    needs an explicit #352-owned policy and issuer capital evidence.
    """
    by_metric: dict[str, MarketReferenceSelectionV1] = {
        selection.policy.metric: selection for selection in selections
    }
    if len(by_metric) != len(selections):
        raise MarketReferenceSelectionError(
            "MARKET_REFERENCE_SELECTION_AMBIGUOUS",
            "reference evidence repeats a selected metric",
        )
    traces: dict[str, TraceV1] = {}
    for evidence in sorted(evidence_items, key=lambda item: item.role):
        if evidence.method != "observed_source":
            continue
        metric = {
            "equity_risk_premium": "country.equity_risk_premium",
            "beta": "industry.unlevered_beta",
        }.get(evidence.role)
        if metric is None:
            raise MarketReferenceSelectionError(
                "MARKET_REFERENCE_ROLE_UNSUPPORTED",
                f"no reference selector is configured for {evidence.role}",
            )
        if evidence.role == "beta":
            raise MarketReferenceSelectionError(
                "MARKET_REFERENCE_BETA_BASIS_UNSUPPORTED",
                "industry unlevered beta cannot authorize issuer equity beta",
            )
        selection = by_metric.get(metric)
        if selection is None:
            raise MarketReferenceSelectionError(
                "MARKET_REFERENCE_SELECTION_MISSING",
                f"reference selection is missing for {evidence.role}",
            )
        if selection.status != "selected" or selection.trace is None:
            raise MarketReferenceSelectionError(
                "MARKET_REFERENCE_SELECTION_REFUSED",
                f"reference selection refused {evidence.role}",
            )
        trace = selection.trace
        if (
            evidence.value != selection.value
            or evidence.content_hash != trace.source_refs[0]
            or evidence.source_id != trace.source_ids[0]
            or evidence.source_uri != trace.source_uris[0]
            or evidence.source_version != trace.source_versions[0]
            or evidence.terms_reference != trace.terms_references[0]
            or evidence.as_of != trace.as_of
            or evidence.available_at != trace.available_at
            or evidence.captured_at != trace.captured_at
        ):
            raise MarketReferenceSelectionError(
                "MARKET_REFERENCE_POLICY_SOURCE_MISMATCH",
                f"observed {evidence.role} differs from selected reference evidence",
            )
        traces[evidence.role] = trace.model_copy(
            update={"source_refs": (*trace.source_refs, selection.output_digest)}
        )
    return traces
