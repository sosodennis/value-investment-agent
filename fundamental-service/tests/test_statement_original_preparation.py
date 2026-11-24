import pytest
from pydantic import ValidationError

from fundamental_service.automatic_source_mapping import AutomaticSecIngestionRequestV1
from fundamental_service.original_preparation import (
    OriginalFilingRuntimeV1,
    OriginalValidationEvidenceV1,
    StatementOriginalPreparationRequestV1,
)
from fundamental_service.snapshots import SnapshotError
from fundamental_service.original_source_plan import (
    OriginalSourcePlan,
    OriginalSourcePlanRequestV1,
)
from test_original_source_plan import configuration
from test_automatic_source_mapping import source_case, statement_source_case
from test_original_preparation import case, execute
from test_annual_discovery_service import _inventory


def mixed_case(tmp_path, monkeypatch, *, retryable=False):
    value = case(tmp_path, monkeypatch, multiple_originals=True)
    annual = value.discovery.read(value.request.annual.artifact_id)
    original = next(
        f for f in annual.selection.selected if f.accession_number.endswith("000001")
    )
    other = next(f for f in annual.selection.selected if f != original)
    current = value.request.runtime
    historical = current.model_copy(
        update={
            "validation_profile_id": "sec-efm-us-dqc-v1.0.0-historical",
            "validation_profile_digest": "b" * 64,
        }
    )
    request = StatementOriginalPreparationRequestV1(
        annual=value.request.annual,
        original_runtimes=tuple(
            sorted(
                (
                    OriginalFilingRuntimeV1(
                        accession_number=original.accession_number, runtime=current
                    ),
                    OriginalFilingRuntimeV1(
                        accession_number=other.accession_number, runtime=historical
                    ),
                ),
                key=lambda item: item.accession_number,
            )
        ),
    )
    calls = []
    delegate = value.acquisition.validate_original_filing

    def validate(request, **kwargs):
        calls.append(request)
        if request.filing == other:
            return OriginalValidationEvidenceV1(
                request=request,
                issue_codes=("SYNTHETIC_TAXONOMY_RESOURCE_UNAVAILABLE",),
                retryable=retryable,
            )
        return delegate(request, **kwargs)

    monkeypatch.setattr(value.acquisition, "validate_original_filing", validate)
    return value, request, original, other, calls


def test_mixed_preparation_retains_one_selection_every_runtime_and_partial_result(
    tmp_path, monkeypatch
):
    value, request, original, other, calls = mixed_case(tmp_path, monkeypatch)
    prepared, publication = execute(value, request)
    assert publication.wrote and len(prepared.filings) == 2
    _, validations = value.service.read_with_validations(prepared.artifact_id)
    by_accession = {v.request.filing.accession_number: v for v in validations}
    assert set(by_accession) == {original.accession_number, other.accession_number}
    assert by_accession[original.accession_number].original is not None
    assert by_accession[other.accession_number].issue_codes == (
        "SYNTHETIC_TAXONOMY_RESOURCE_UNAVAILABLE",
    )
    assert all(
        v.request.runtime == request.runtime_for(accession)
        for accession, v in by_accession.items()
    )
    assert prepared.request.annual == value.request.annual
    before = _inventory(tmp_path)
    provider_calls = value.state.provider_calls, value.state.parser_calls
    again, reused = execute(value, request)
    assert again == prepared and not reused.wrote
    assert _inventory(tmp_path) == before
    assert len(calls) == 2
    assert (value.state.provider_calls, value.state.parser_calls) == provider_calls


@pytest.mark.parametrize("change", ["omit", "add", "catalog", "revision"])
def test_mixed_runtime_must_cover_exact_frozen_original_universe(
    tmp_path, monkeypatch, change
):
    value, request, *_ = mixed_case(tmp_path, monkeypatch)
    runtimes = list(request.original_runtimes)
    expected = "ORIGINAL_RUNTIME_CATALOG_MISMATCH"
    if change == "omit":
        runtimes.pop()
        expected = "ORIGINAL_RUNTIME_SELECTION_MISMATCH"
    elif change == "add":
        runtimes.append(
            runtimes[-1].model_copy(update={"accession_number": "0000000001-26-999998"})
        )
        expected = "ORIGINAL_RUNTIME_SELECTION_MISMATCH"
    else:
        runtime = runtimes[0].runtime.model_copy(
            update={"supported_filing_years": (2025,)}
            if change == "catalog"
            else {"declared_source_revision": "c" * 40}
        )
        runtimes[0] = runtimes[0].model_copy(update={"runtime": runtime})
    invalid = StatementOriginalPreparationRequestV1(
        annual=request.annual,
        original_runtimes=tuple(sorted(runtimes, key=lambda r: r.accession_number)),
    )
    before = value.state.parser_calls
    result, _ = execute(value, invalid)
    assert result.filings == () and expected in result.issue_codes
    assert value.state.parser_calls == before


def test_duplicate_or_unordered_per_original_runtimes_are_rejected(
    tmp_path, monkeypatch
):
    _, request, *_ = mixed_case(tmp_path, monkeypatch)
    for runtimes in (
        request.original_runtimes * 2,
        tuple(reversed(request.original_runtimes)),
    ):
        with pytest.raises(ValidationError, match="distinct ordered"):
            StatementOriginalPreparationRequestV1(
                annual=request.annual, original_runtimes=runtimes
            )


def test_statement_can_read_valid_original_when_another_original_needs_retry(
    tmp_path, monkeypatch
):
    value, request, original, _, _ = mixed_case(tmp_path, monkeypatch, retryable=True)
    prepared, _ = execute(value, request)
    statement, *_ = statement_source_case(tmp_path / "statement-request", monkeypatch)
    statement = statement.model_copy(
        update={
            "original_preparation": value.service.reference(
                prepared.artifact_id, "sec-original-preparation-v1"
            )
        }
    )
    assert prepared.retryable
    with value.acquisition.evidence_operation():
        selected = value.acquisition._prepared_filing(statement)
        assert selected.accession_number == original.accession_number


def test_statement_preparation_cannot_authorize_valuation_source(tmp_path, monkeypatch):
    value, request, *_ = mixed_case(tmp_path, monkeypatch)
    prepared, _ = execute(value, request)
    valuation, *_ = source_case(tmp_path / "valuation-request")
    valuation = AutomaticSecIngestionRequestV1.model_validate(
        valuation.model_dump()
        | {
            "original_preparation": value.service.reference(
                prepared.artifact_id, "sec-original-preparation-v1"
            )
        }
    )
    with value.acquisition.evidence_operation(), pytest.raises(SnapshotError) as error:
        value.acquisition._prepared_filing(valuation)
    assert error.value.code == "ORIGINAL_PREPARATION_PURPOSE_MISMATCH"


def test_statement_preparation_cannot_compile_a_valuation_source_plan(
    tmp_path, monkeypatch
):
    value, request, *_ = mixed_case(tmp_path, monkeypatch)
    prepared, _ = execute(value, request)
    compiler = OriginalSourcePlan(
        originals=value.service, artifacts=value.artifacts, compilation_lock=value.locks
    )
    plan = OriginalSourcePlanRequestV1(
        original_preparation=value.service.reference(
            prepared.artifact_id, "sec-original-preparation-v1"
        ),
        configuration=configuration(),
        runtime_source_revision=value.request.runtime.declared_source_revision,
    )
    before = _inventory(tmp_path)
    with pytest.raises(SnapshotError) as error:
        compiler.execute(plan)
    assert error.value.code == "ORIGINAL_SOURCE_PLAN_PURPOSE_MISMATCH"
    assert _inventory(tmp_path) == before
