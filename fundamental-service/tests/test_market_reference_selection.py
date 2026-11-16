from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import json
from decimal import Context, Decimal, Inexact, localcontext

import pytest

from fundamental_service.damodaran_source import (
    DAMODARAN_BETA_PROFILE,
    DAMODARAN_SOURCE,
    DAMODARAN_TERMS,
    DamodaranReferenceProvider,
)
from fundamental_service.market_reference import (
    MarketReferenceVintageV1,
    ReferenceRowV1,
)
from fundamental_service.market_reference_selection import (
    IssuerMarketReferencePlanV1,
    MarketReferenceSelectionError,
    MarketReferenceSelectionPolicyV1,
    select_issuer_market_references,
    select_market_reference,
    verify_market_reference_policy_evidence,
)
from fundamental_service.contracts import MarketPolicyInputsV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from market_policy_fixtures import synthetic_market_inputs
from test_source_admission import _admit as country_admission
from fundamental_service.source_admission import (
    SourceUsePolicyV1,
    SourceUseRuleV1,
    TermsRequirementV1,
    admit_reference_source,
)
from fundamental_service.source_evidence import RetainedSourceV1, SourceArtifactV1
from reference_source_fixtures import beta_xls


CAPTURE = datetime(2026, 11, 12, tzinfo=UTC)
VALUATION = datetime(2026, 11, 13, tzinfo=UTC)
TERMS = RetainedSourceV1(
    source_id="synthetic-terms",
    uri="https://example.test/terms",
    source_version="synthetic-terms-v1",
    terms_reference="https://example.test/terms",
    content=b"synthetic permission fixture",
    captured_at=CAPTURE,
)


class AlternateBetaProvider:
    provider_id = "alternate-beta-provider"

    def supports(self, metric):
        return metric == "industry.unlevered_beta"

    def reproduce_vintage(self, *, metric, sources):
        source = sources[0]
        declaration = json.loads(source.content)
        digest = hashlib.sha256(source.content).hexdigest()
        value = declaration["value"]
        return MarketReferenceVintageV1.build(
            metric=metric,
            population=declaration.get("population", "us-companies"),
            unit="multiple",
            provider_id=self.provider_id,
            source_version=source.source_version,
            source_updated_on=source.captured_at.date(),
            available_at=source.captured_at,
            captured_at=source.captured_at,
            artifacts=(
                SourceArtifactV1(
                    source_id=source.source_id,
                    uri=source.uri,
                    source_version=source.source_version,
                    terms_reference=source.terms_reference,
                    captured_at=source.captured_at,
                    content_sha256=digest,
                ),
            ),
            rows=(
                ReferenceRowV1(
                    subject="Retail (Special Lines)",
                    subject_kind="industry",
                    value=Decimal(value) if value is not None else None,
                    missing_reason="source_marker" if value is None else None,
                    raw_value=value if value is not None else "NA",
                    numeric_encoding="decimal_text" if value is not None else "missing",
                    value_basis="published_cell",
                    number_format="0.00",
                    locator="$.value",
                    source_sha256=digest,
                ),
            ),
        )


def _admission(
    *,
    provider=None,
    at=CAPTURE,
    value=None,
    population="us-companies",
    purpose="valuation_preparation",
    granted_purpose="valuation_preparation",
    policy_version="selection-test-v1",
):
    provider = provider or DamodaranReferenceProvider()
    source = RetainedSourceV1(
        source_id=DAMODARAN_SOURCE
        if isinstance(provider, DamodaranReferenceProvider)
        else "json-beta",
        uri="https://pages.stern.nyu.edu/~adamodar/pc/archives/betas25.xls"
        if isinstance(provider, DamodaranReferenceProvider)
        else "https://example.test/reference.json",
        source_version=DAMODARAN_BETA_PROFILE
        if isinstance(provider, DamodaranReferenceProvider)
        else "synthetic-json-v1",
        terms_reference=DAMODARAN_TERMS
        if isinstance(provider, DamodaranReferenceProvider)
        else TERMS.uri,
        content=beta_xls()
        if isinstance(provider, DamodaranReferenceProvider)
        else canonical_bytes({"value": value, "population": population}),
        captured_at=at,
    )
    rule = SourceUseRuleV1(
        rule_id="synthetic-beta-use",
        provider_id=provider.provider_id,
        metric_id="industry.unlevered_beta",
        population="us-companies",
        source_id=source.source_id,
        source_version=source.source_version,
        terms_reference=source.terms_reference,
        permitted_uses=(granted_purpose,),
        terms=(
            TermsRequirementV1(
                uri=TERMS.uri,
                content_sha256=hashlib.sha256(TERMS.content).hexdigest(),
            ),
        ),
        required_notices=("Synthetic selection test only",),
        basis="Synthetic source-use rule",
    )
    policy = SourceUsePolicyV1(policy_version=policy_version, rules=(rule,))
    admission = admit_reference_source(
        provider,
        metric="industry.unlevered_beta",
        sources=(source,),
        terms=(TERMS,),
        valuation_at=VALUATION,
        intended_use=purpose,
        policy=policy,
    )
    return admission


def _selection_policy(*, subject="Retail (Special Lines)", max_age=730):
    return MarketReferenceSelectionPolicyV1(
        policy_version="industry-row-exact-v1",
        metric="industry.unlevered_beta",
        population="us-companies",
        subject_kind="industry",
        subject=subject,
        maximum_age_days=max_age,
    )


def test_selection_is_provider_neutral_and_binds_row_and_original_source():
    first = _admission()
    second = _admission(
        provider=AlternateBetaProvider(),
        value=str(Decimal.from_float(1.0024856714394297)),
    )
    selected_first = select_market_reference(
        (first,), policy=_selection_policy(), valuation_at=VALUATION
    )
    selected_second = select_market_reference(
        (second,), policy=_selection_policy(), valuation_at=VALUATION
    )
    assert selected_first.status == selected_second.status == "selected"
    assert (
        selected_first.value
        == selected_second.value
        == Decimal.from_float(1.0024856714394297)
    )
    assert (
        selected_first.trace.source_refs[0] == first.vintage.artifacts[0].content_sha256
    )
    assert (
        selected_second.trace.source_refs[0]
        == second.vintage.artifacts[0].content_sha256
    )
    assert selected_first.output_digest != selected_second.output_digest
    assert selected_first == type(selected_first).model_validate_json(
        canonical_bytes(selected_first)
    )


def test_missing_rows_stale_sources_and_future_sources_are_retained_as_refusals():
    admission = _admission()
    missing = select_market_reference(
        (admission,),
        policy=_selection_policy(subject="Unknown issuer industry"),
        valuation_at=VALUATION,
    )
    stale = select_market_reference(
        (admission,),
        policy=_selection_policy(max_age=0),
        valuation_at=VALUATION,
    )
    future = select_market_reference(
        (admission,),
        policy=_selection_policy(),
        valuation_at=CAPTURE - timedelta(microseconds=1),
    )
    assert missing.issue_codes == ("MARKET_REFERENCE_SUBJECT_UNAVAILABLE",)
    assert stale.issue_codes == ("MARKET_REFERENCE_SOURCE_STALE",)
    assert future.issue_codes == ("MARKET_REFERENCE_SOURCE_UNAVAILABLE",)
    assert all(
        item.status == "refused" and item.trace is None
        for item in (missing, stale, future)
    )


def test_issuer_bundle_is_order_independent_and_retains_partial_outcomes():
    admission = _admission()
    known = _selection_policy()
    missing = MarketReferenceSelectionPolicyV1(
        policy_version="country-row-exact-v1",
        metric="country.equity_risk_premium",
        population="countries",
        subject_kind="country",
        subject="Unmapped country",
        maximum_age_days=730,
    )
    first = IssuerMarketReferencePlanV1(
        issuer_id="CIK0000000001",
        policy_id="fcff_dcf-us-gaap-public-v3",
        valuation_at=VALUATION,
        selections=(missing, known),
    )
    reordered = IssuerMarketReferencePlanV1(
        issuer_id="CIK0000000001",
        policy_id="fcff_dcf-us-gaap-public-v3",
        valuation_at=VALUATION,
        selections=(known, missing),
    )
    result = select_issuer_market_references(
        first, admissions=(country_admission(), admission, admission)
    )
    replay = select_issuer_market_references(
        reordered, admissions=(admission, country_admission())
    )
    assert result.status == "partial"
    assert result.issue_codes == ("MARKET_REFERENCE_SUBJECT_UNAVAILABLE",)
    assert [item.status for item in result.selections] == ["refused", "selected"]
    assert result.input_digest == replay.input_digest
    assert result.output_digest == replay.output_digest


def test_tied_latest_vintages_and_invalid_policy_do_not_select_a_reference():
    first = _admission()
    second = _admission(provider=AlternateBetaProvider(), value="1.01")
    selected = select_market_reference(
        (first, second), policy=_selection_policy(), valuation_at=VALUATION
    )
    assert selected.issue_codes == ("MARKET_REFERENCE_SOURCE_AMBIGUOUS",)
    assert selected.row is None
    with pytest.raises(ValueError, match="exact metric/subject kind"):
        MarketReferenceSelectionPolicyV1(
            policy_version="invalid",
            metric="industry.unlevered_beta",
            population="us-companies",
            subject_kind="country",
            subject="United States",
            maximum_age_days=1,
        )


def test_latest_missing_cell_is_retained_without_using_an_older_populated_vintage():
    old = _admission(
        provider=AlternateBetaProvider(), at=CAPTURE - timedelta(days=1), value="0.8"
    )
    current = _admission(provider=AlternateBetaProvider(), value=None)
    selected = select_market_reference(
        (old, current), policy=_selection_policy(), valuation_at=VALUATION
    )
    assert selected.issue_codes == ("MARKET_REFERENCE_VALUE_MISSING",)
    assert selected.row.missing_reason == "source_marker"
    assert selected.row.raw_value == "NA"
    assert selected.vintage_digest == current.vintage.content_digest
    assert selected.value is None


@pytest.mark.parametrize("change", ["population", "purpose", "refused"])
def test_ineligible_reference_admissions_cannot_authorize_a_selection(change):
    kwargs = {"provider": AlternateBetaProvider(), "value": "1.1"}
    if change == "population":
        kwargs["population"] = "individual-companies"
    else:
        kwargs["purpose"] = "derived_valuation_display"
        if change == "purpose":
            kwargs["granted_purpose"] = "derived_valuation_display"
    admission = _admission(**kwargs)
    selected = select_market_reference(
        (admission,), policy=_selection_policy(), valuation_at=VALUATION
    )
    assert selected.issue_codes == ("MARKET_REFERENCE_SOURCE_UNAVAILABLE",)


def test_same_vintage_with_conflicting_admissions_is_not_silently_selected():
    first = _admission()
    second = _admission(policy_version="different-source-use-v1")
    selected = select_market_reference(
        (first, second), policy=_selection_policy(), valuation_at=VALUATION
    )
    assert selected.issue_codes == ("MARKET_REFERENCE_ADMISSION_AMBIGUOUS",)


def test_persistent_partial_bundle_repeats_without_new_bytes_or_modified_files(
    tmp_path,
):
    from fundamental_service.replay import ArtifactStore

    plan = IssuerMarketReferencePlanV1(
        issuer_id="CIK0000000001",
        policy_id="fcff_dcf-us-gaap-public-v3",
        valuation_at=VALUATION,
        selections=(_selection_policy(),),
    )
    admissions = (_admission(),)
    result = select_issuer_market_references(plan, admissions=admissions)
    store = ArtifactStore(tmp_path)
    receipt = store.put_with_receipt("reference-" + result.output_digest, result)
    inventory = {
        str(x): (x.read_bytes(), x.stat().st_mtime_ns)
        for x in tmp_path.rglob("*")
        if x.is_file()
    }
    with localcontext(Context(prec=3, traps=[Inexact])):
        assert select_issuer_market_references(plan, admissions=admissions) == result

    def replay(_):
        selected = select_issuer_market_references(plan, admissions=admissions)
        return store.put_with_receipt("reference-" + selected.output_digest, selected)

    with ThreadPoolExecutor(max_workers=4) as pool:
        repeats = tuple(pool.map(replay, range(8)))
    assert receipt.wrote and not any(x.wrote for x in repeats)
    assert all(x.artifact == receipt.artifact for x in repeats)
    assert inventory == {
        str(x): (x.read_bytes(), x.stat().st_mtime_ns)
        for x in tmp_path.rglob("*")
        if x.is_file()
    }
    assert result.output_digest == sha256_digest(
        result.model_dump(exclude={"output_digest"})
    )


def test_country_erp_can_bind_an_observed_policy_role_with_the_same_trace():
    admission = country_admission()
    policy = MarketReferenceSelectionPolicyV1(
        policy_version="country-row-exact-v1",
        metric="country.equity_risk_premium",
        population="countries",
        subject_kind="country",
        subject="United States",
        maximum_age_days=730,
    )
    selection = select_market_reference(
        (admission,), policy=policy, valuation_at=VALUATION
    )
    assert selection.status == "selected"
    assert selection.trace is not None
    payload = synthetic_market_inputs().model_dump(mode="python")
    evidence = next(
        item for item in payload["evidence"] if item["role"] == "equity_risk_premium"
    )
    trace = selection.trace
    evidence.update(
        method="observed_source",
        value=selection.value,
        source_id=trace.source_ids[0],
        source_uri=trace.source_uris[0],
        content_hash=trace.source_refs[0],
        source_version=trace.source_versions[0],
        terms_reference=trace.terms_references[0],
        as_of=trace.as_of,
        available_at=trace.available_at,
        captured_at=trace.captured_at,
        rationale="Exact country row selected from an admitted reference vintage",
    )
    payload["equity_risk_premium"] = selection.value
    inputs = MarketPolicyInputsV1.model_validate(payload)
    traces = verify_market_reference_policy_evidence(
        inputs.evidence, selections=(selection,)
    )
    assert traces["equity_risk_premium"].source_refs[-1] == selection.output_digest


def test_unlevered_beta_cannot_be_silently_promoted_to_equity_beta():
    admission = _admission()
    selection = select_market_reference(
        (admission,), policy=_selection_policy(), valuation_at=VALUATION
    )
    assert selection.status == "selected"
    assert selection.trace is not None
    payload = synthetic_market_inputs().model_dump(mode="python")
    evidence = next(item for item in payload["evidence"] if item["role"] == "beta")
    trace = selection.trace
    evidence.update(
        method="observed_source",
        value=selection.value,
        source_id=trace.source_ids[0],
        source_uri=trace.source_uris[0],
        content_hash=trace.source_refs[0],
        source_version=trace.source_versions[0],
        terms_reference=trace.terms_references[0],
        as_of=trace.as_of,
        available_at=trace.available_at,
        captured_at=trace.captured_at,
        rationale="Unlevered beta fixture",
    )
    payload["beta"] = selection.value
    inputs = MarketPolicyInputsV1.model_validate(payload)
    with pytest.raises(MarketReferenceSelectionError) as error:
        verify_market_reference_policy_evidence(
            inputs.evidence, selections=(selection,)
        )
    assert error.value.code == "MARKET_REFERENCE_BETA_BASIS_UNSUPPORTED"
