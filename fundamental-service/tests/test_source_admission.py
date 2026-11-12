from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.damodaran_source import (
    DAMODARAN_COUNTRY_PROFILE,
    DAMODARAN_SOURCE,
    DAMODARAN_TERMS,
    DamodaranReferenceProvider,
)
from fundamental_service.free_source_policy import free_market_source_policy
from fundamental_service.macro_series import MacroObservationV1, MacroSeriesVintageV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.source_admission import (
    SourceAdmissionV1,
    SourceUsePolicyV1,
    SourceUseRuleV1,
    TermsRequirementV1,
    admit_macro_source,
    admit_reference_source,
)
from fundamental_service.source_evidence import RetainedSourceV1, SourceArtifactV1
from reference_source_fixtures import country_xlsx

CAPTURE = datetime(2026, 11, 12, tzinfo=UTC)
METRIC = "country.equity_risk_premium"


def _source() -> RetainedSourceV1:
    return RetainedSourceV1(
        source_id=DAMODARAN_SOURCE,
        uri="https://pages.stern.nyu.edu/~adamodar/pc/archives/ctryprem24.xlsx",
        source_version=DAMODARAN_COUNTRY_PROFILE,
        terms_reference=DAMODARAN_TERMS,
        content=country_xlsx(),
        captured_at=CAPTURE,
    )


def _terms(
    uri: str = "https://example.test/terms", content: bytes = b"synthetic terms"
) -> RetainedSourceV1:
    return RetainedSourceV1(
        source_id="synthetic-terms",
        uri=uri,
        source_version="synthetic-v1",
        terms_reference=uri,
        content=content,
        captured_at=CAPTURE,
    )


def _reference_policy() -> SourceUsePolicyV1:
    original = free_market_source_policy()
    selected = next(x for x in original.rules if x.metric_id == METRIC)
    rule = selected.model_copy(
        update={
            "terms": (
                TermsRequirementV1(
                    uri=_terms().uri,
                    content_sha256=hashlib.sha256(_terms().content).hexdigest(),
                ),
            ),
        }
    )
    return SourceUsePolicyV1(policy_version="synthetic-test-only", rules=(rule,))


def _admit(**updates) -> SourceAdmissionV1:
    kwargs = dict(
        metric=METRIC,
        sources=(_source(),),
        terms=(_terms(),),
        valuation_at=CAPTURE,
        policy=_reference_policy(),
    )
    kwargs.update(updates)
    return admit_reference_source(DamodaranReferenceProvider(), **kwargs)


def test_reference_admission_retains_values_missing_rows_notices_and_unchanged_dates():
    result = _admit()
    assert result.status == "admitted"
    assert result.issue_codes == ()
    assert result.vintage.available_at == CAPTURE
    assert result.vintage.source_updated_on == date(2025, 1, 1)
    rows = {x.subject: x for x in result.vintage.rows}
    assert rows["United States"].value == Decimal("4.3299999999999998E-2")
    assert rows["Missing country"].missing_reason == "source_marker"
    assert result.source_checks[0].required_notices
    assert "Underlying company-level" in result.source_checks[0].required_notices[0]
    assert result == SourceAdmissionV1.model_validate_json(canonical_bytes(result))
    assert _admit(expected=result) == result


@pytest.mark.parametrize(
    "purpose,status",
    [
        ("valuation_preparation", "admitted"),
        ("derived_valuation_display", "admitted"),
        ("raw_data_redistribution", "refused"),
    ],
)
def test_use_is_separate_from_the_provider_and_raw_distribution_is_not_granted(
    purpose, status
):
    result = _admit(intended_use=purpose)
    assert result.status == status
    if status == "refused":
        assert result.issue_codes == ("SOURCE_USE_PURPOSE_UNSUPPORTED",)


@pytest.mark.parametrize(
    "kind,code",
    [
        ("missing", "SOURCE_USE_TERMS_MISSING"),
        ("changed", "SOURCE_USE_TERMS_CHANGED"),
        ("ambiguous", "SOURCE_USE_TERMS_AMBIGUOUS"),
    ],
)
def test_terms_are_reproduced_from_exact_retained_bytes(kind, code):
    supplied = {
        "missing": (),
        "changed": (_terms(content=b"different conditions"),),
        "ambiguous": (_terms(), _terms(content=b"conflicting conditions")),
    }[kind]
    result = _admit(terms=supplied)
    assert result.status == "refused"
    assert result.issue_codes == (code,)
    assert result.vintage is not None
    assert result.request.terms_artifacts == tuple(
        sorted(result.request.terms_artifacts, key=sha256_digest)
    )


def test_current_terms_capture_does_not_backdate_data_availability():
    result = _admit(valuation_at=datetime(2025, 4, 1, tzinfo=UTC))
    assert result.status == "refused"
    assert result.issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
    assert result.vintage.available_at == CAPTURE
    assert not result.source_checks[0].issue_codes


def test_production_catalog_never_admits_synthetic_terms():
    result = _admit(policy=free_market_source_policy())
    assert result.status == "refused"
    assert result.issue_codes == ("SOURCE_USE_TERMS_MISSING",)
    assert result.request.policy_version == "free-market-source-use-v2"


def test_unknown_or_ambiguous_trusted_rule_is_not_provider_permission():
    missing = _admit(policy=SourceUsePolicyV1(policy_version="empty-test"))
    assert missing.issue_codes == ("SOURCE_USE_POLICY_MISSING",)
    rule = _reference_policy().rules[0]
    alternate = rule.model_copy(update={"rule_id": rule.rule_id + "-other"})
    policy = SourceUsePolicyV1(policy_version="ambiguous-test", rules=(rule, alternate))
    result = _admit(policy=policy)
    assert result.issue_codes == ("SOURCE_USE_POLICY_AMBIGUOUS",)
    assert len(result.source_checks[0].rule_ids) == 2


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("content", b"corrupt original", "REFERENCE_SOURCE_INVALID"),
        ("source_id", "unconfigured", "REFERENCE_SOURCE_INVALID"),
        ("source_version", "unconfigured", "REFERENCE_SOURCE_INVALID"),
        ("terms_reference", "wrong terms", "REFERENCE_SOURCE_INVALID"),
        ("uri", "https://example.test/reference.xlsx", "SOURCE_QUERY_INVALID"),
    ],
)
def test_failed_reproduction_retains_source_identity_hash_and_stable_errors(
    field, value, code
):
    original = replace(_source(), **{field: value})
    result = _admit(sources=(original,))
    assert result.status == "refused"
    assert result.issue_codes == (
        code,
        "SOURCE_REPRODUCTION_FAILED",
    )
    assert result.vintage is None
    assert (
        result.request.source_artifacts[0].content_sha256
        == hashlib.sha256(original.content).hexdigest()
    )
    assert not result.source_checks
    assert _admit(sources=(original,)) == result


def test_rehashed_forged_admission_cannot_replace_source_reproduction():
    result = _admit()
    payload = result.model_dump()
    vintage = payload["vintage"]
    row = next(x for x in vintage["rows"] if x["subject"] == "United States")
    row.update(value=Decimal("0.9"), raw_value="0.9")
    vintage["content_digest"] = sha256_digest(
        {k: v for k, v in vintage.items() if k != "content_digest"}
    )
    payload["output_digest"] = sha256_digest(
        {k: v for k, v in payload.items() if k != "output_digest"}
    )
    forged = SourceAdmissionV1.model_validate(payload)
    with pytest.raises(SnapshotError) as error:
        _admit(expected=forged)
    assert error.value.code == "SOURCE_ADMISSION_REPLAY_MISMATCH"


def test_changed_original_is_reproduced_before_comparing_an_existing_admission():
    result = _admit()
    changed = replace(_source(), content=country_xlsx(change="formula"))
    with pytest.raises(SnapshotError) as error:
        _admit(sources=(changed,), expected=result)
    assert error.value.code == "SOURCE_ADMISSION_REPLAY_MISMATCH"


class JsonRateProvider:
    """Independent provider fixture; no knowledge of the source-use catalog."""

    provider_id = "synthetic-json-rate"

    def supports(self, series_id: str) -> bool:
        return series_id == "us.treasury_par_yield_10y"

    def reproduce_vintage(
        self, *, series_id: str, sources: tuple[RetainedSourceV1, ...]
    ) -> MacroSeriesVintageV1:
        source = next(x for x in sources if x.source_id == "synthetic-rate")
        metadata = next(x for x in sources if x.source_id == "synthetic-rate-metadata")
        declaration = json.loads(metadata.content)
        if declaration["unit"] != "percent":
            raise ValueError("unknown unit")
        return MacroSeriesVintageV1.build(
            series_id=series_id,
            provider_id=self.provider_id,
            frequency="daily",
            unit=declaration["unit"],
            source_version="synthetic-json-v1",
            available_at=source.captured_at,
            captured_at=source.captured_at,
            artifacts=tuple(
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
            observations=(
                MacroObservationV1(
                    series_id=series_id,
                    period_start=date(2026, 11, 11),
                    period_end=date(2026, 11, 11),
                    value=Decimal(source.content.decode()),
                    unit=declaration["unit"],
                    source_sha256=hashlib.sha256(source.content).hexdigest(),
                ),
            ),
        )


def _macro_inputs():
    originals = tuple(
        replace(
            _terms(),
            source_id=name,
            uri="https://example.test/" + name,
            source_version="synthetic-json-v1",
            content=content,
        )
        for name, content in (
            ("synthetic-rate", b"4.25"),
            ("synthetic-rate-metadata", b'{"unit":"percent"}'),
        )
    )
    rules = tuple(
        SourceUseRuleV1(
            rule_id=x.source_id,
            provider_id=JsonRateProvider.provider_id,
            metric_id="us.treasury_par_yield_10y",
            population="us.treasury_par_yield_10y",
            source_id=x.source_id,
            source_version=x.source_version,
            terms_reference=x.terms_reference,
            terms=(
                TermsRequirementV1(
                    uri=_terms().uri,
                    content_sha256=hashlib.sha256(_terms().content).hexdigest(),
                ),
            ),
            permitted_uses=("valuation_preparation",),
            required_notices=("Synthetic test source only",),
            basis="Synthetic deployment-owned test grant",
        )
        for x in originals
    )
    policy = SourceUsePolicyV1(policy_version="synthetic-test-only", rules=rules)
    return dict(
        series_id="us.treasury_par_yield_10y",
        sources=originals,
        terms=(_terms(),),
        policy=policy,
        valuation_at=CAPTURE,
    )


def test_alternative_macro_provider_and_multi_original_order_use_the_same_admission_contract():
    inputs = _macro_inputs()
    result = admit_macro_source(JsonRateProvider(), **inputs)
    assert result.status == "admitted"
    assert result.vintage.observations[0].value == Decimal("4.25")
    assert len(result.source_checks) == 2
    reordered = {**inputs, "sources": tuple(reversed(inputs["sources"]))}
    assert admit_macro_source(JsonRateProvider(), **reordered) == result
    assert canonical_bytes(
        admit_macro_source(JsonRateProvider(), **inputs, expected=result)
    ) == canonical_bytes(result)


def test_every_original_requires_a_source_use_rule():
    inputs = _macro_inputs()
    inputs["policy"] = inputs["policy"].model_copy(
        update={"rules": inputs["policy"].rules[:1]}
    )
    result = admit_macro_source(JsonRateProvider(), **inputs)
    assert result.status == "refused"
    assert result.issue_codes == ("SOURCE_USE_POLICY_MISSING",)
    assert len(result.source_checks) == 2
    assert sum(bool(x.issue_codes) for x in result.source_checks) == 1


def test_changed_population_cannot_reuse_a_country_aggregate_grant():
    policy = _reference_policy()
    rule = policy.rules[0].model_copy(update={"population": "individual-companies"})
    result = _admit(policy=policy.model_copy(update={"rules": (rule,)}))
    assert result.issue_codes == ("SOURCE_USE_POLICY_MISSING",)


def test_timezone_and_noncanonical_output_are_rejected():
    with pytest.raises(ValidationError, match="valuation timezone"):
        _admit(valuation_at=datetime(2026, 11, 12))
    result = _admit()
    payload = result.model_dump()
    payload["output_digest"] = "0" * 64
    with pytest.raises(ValidationError, match="digest"):
        SourceAdmissionV1.model_validate(payload)


def test_rehashed_admitted_label_cannot_omit_known_source_refusals():
    result = _admit(intended_use="raw_data_redistribution")
    payload = result.model_dump()
    payload.update(status="admitted", issue_codes=())
    payload["output_digest"] = sha256_digest(
        {k: v for k, v in payload.items() if k != "output_digest"}
    )
    with pytest.raises(ValidationError, match="omits a retained refusal"):
        SourceAdmissionV1.model_validate(payload)
