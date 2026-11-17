"""Checked preparations retain exact results, live metadata and bounded lifetime."""

import pytest

from fundamental_service.original_preparation import OriginalPreparationReads
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError
from test_original_preparation import case, execute


def test_original_producer_shares_build_proof_only_within_one_operation(
    tmp_path, monkeypatch
):
    import fundamental_service.parser_action_identity as identity

    proofs = []
    monkeypatch.setattr(
        identity, "_immutable_build_configuration", lambda: ("image", ())
    )
    monkeypatch.setattr(
        identity, "_runtime_identity", lambda **kwargs: proofs.append(True) or "2" * 64
    )
    for number in range(2):
        value = case(tmp_path / str(number), monkeypatch, multiple_originals=True)
        validate = value.acquisition.validate_original_filing
        ingest = value.acquisition.ingestion.validate_filing
        consumed = []
        ingestion_builds = []

        def validate_original(request, **kwargs):
            builds = kwargs["build_checks"]
            builds.current()
            consumed.append(builds)
            return validate(request, **kwargs)

        def validate_filing(**kwargs):
            ingestion_builds.append(kwargs["build_checks"])
            return ingest(**kwargs)

        monkeypatch.setattr(
            value.acquisition, "validate_original_filing", validate_original
        )
        monkeypatch.setattr(
            value.acquisition.ingestion, "validate_filing", validate_filing
        )
        with value.service.evidence_operation() as reads:
            result, receipt = value.service.execute(
                value.request, deadline_at=value.deadline, reads=reads
            )
            assert receipt.wrote and len(result.filings) == 2
            assert consumed == [reads.builds, reads.builds]
            assert ingestion_builds and all(b is reads.builds for b in ingestion_builds)
            assert len(proofs) == number + 1
        assert reads.closed
        with pytest.raises(RuntimeError, match="scope has ended"):
            value.service.execute(
                value.request, deadline_at=value.deadline, reads=reads
            )


@pytest.mark.parametrize("scoped", (False, True))
def test_original_build_configuration_change_refuses_before_publication(
    tmp_path, monkeypatch, scoped
):
    import fundamental_service.parser_action_identity as identity

    value = case(tmp_path, monkeypatch, multiple_originals=True)
    configuration = ["original image"]
    monkeypatch.setattr(
        identity, "_immutable_build_configuration", lambda: (configuration[0], ())
    )
    monkeypatch.setattr(identity, "_runtime_identity", lambda **kwargs: "2" * 64)
    validate = value.acquisition.ingestion.validate_filing

    def validate_filing(**kwargs):
        kwargs["build_checks"].current()
        result = validate(**kwargs)
        configuration[0] = "changed image configuration"
        return result

    monkeypatch.setattr(value.acquisition.ingestion, "validate_filing", validate_filing)
    scope = OriginalPreparationReads(value.service) if scoped else None
    try:
        with pytest.raises(
            identity.IncompleteParserClosure, match="configuration changed"
        ):
            value.service.execute(
                value.request, deadline_at=value.deadline, reads=scope
            )
        with pytest.raises(SnapshotError) as missing:
            value.artifacts.get(f"original-preparation:{value.request.digest}")
        assert missing.value.code == "ARTIFACT_NOT_FOUND"
    finally:
        if scope is not None:
            scope.clear()


@pytest.mark.parametrize("change_before_publication", (False, True))
def test_acquisition_build_scope_is_rechecked_before_domain_publication(
    tmp_path, monkeypatch, change_before_publication
):
    import fundamental_service.parser_action_identity as identity
    from test_automatic_source_acquisition import acquisition_case, acquire

    request, acquisition, _, metadata, _ = acquisition_case(tmp_path, monkeypatch)
    configuration = ["image"]
    monkeypatch.setattr(
        identity, "_immutable_build_configuration", lambda: (configuration[0], ())
    )
    monkeypatch.setattr(identity, "_runtime_identity", lambda **kwargs: "2" * 64)
    prepare = acquisition.ingestion.prepare_filing

    def prepare_filing(**kwargs):
        builds = kwargs["build_checks"]
        assert builds is acquisition._original_reads.get().builds
        builds.current()
        result = prepare(**kwargs)
        if change_before_publication:
            configuration[0] = "changed image configuration"
        return result

    monkeypatch.setattr(acquisition.ingestion, "prepare_filing", prepare_filing)
    if change_before_publication:
        with pytest.raises(
            identity.IncompleteParserClosure, match="configuration changed"
        ):
            with acquisition.evidence_operation():
                acquire(request, acquisition)
        assert not metadata.acquisitions and not metadata.snapshots
    else:
        with acquisition.evidence_operation():
            result = acquire(request, acquisition)
        assert result.snapshot_id in metadata.snapshots and metadata.acquisitions
    assert acquisition._original_reads.get() is None


def test_producer_only_scope_rechecks_build_at_exit_with_an_empty_read_journal(
    tmp_path, monkeypatch
):
    import fundamental_service.parser_action_identity as identity

    value = case(tmp_path, monkeypatch)
    configuration = ["image"]
    monkeypatch.setattr(
        identity, "_immutable_build_configuration", lambda: (configuration[0], ())
    )
    monkeypatch.setattr(identity, "_runtime_identity", lambda **kwargs: "2" * 64)
    validate = value.acquisition.ingestion.validate_filing

    def validate_filing(**kwargs):
        kwargs["build_checks"].current()
        return validate(**kwargs)

    monkeypatch.setattr(value.acquisition.ingestion, "validate_filing", validate_filing)
    with pytest.raises(identity.IncompleteParserClosure, match="configuration changed"):
        with value.service.evidence_operation() as reads:
            _, receipt = value.service.execute(
                value.request, deadline_at=value.deadline, reads=reads
            )
            assert receipt.wrote and reads._journal.tell() == 0
            configuration[0] = "changed after producer returned"
    assert reads.closed


def test_filing_lookup_reuses_one_complete_owner_validation(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch, multiple_originals=True)
    prepared, _ = execute(value)
    expected = value.service.read_with_validations(prepared.artifact_id)
    calls = []
    original = type(value.service).read_validation

    def read_validation(owner, artifact_id, **kwargs):
        calls.append(artifact_id)
        return original(owner, artifact_id, **kwargs)

    monkeypatch.setattr(type(value.service), "read_validation", read_validation)
    scope = OriginalPreparationReads(value.service)
    for _ in range(4):
        for validation in expected[1]:
            actual = scope.filing(
                prepared.artifact_id, validation.request.filing.accession_number
            )
            assert actual[0] == prepared and actual[2] == validation
    assert len(calls) == len(expected[1])
    assert canonical_bytes(scope.read(prepared.artifact_id)) == canonical_bytes(
        expected
    )
    scope.finish()
    assert not scope.entries and scope.retained_bytes == 0
    with pytest.raises(RuntimeError, match="ended"):
        scope.read(prepared.artifact_id)


def test_current_dependency_revocation_refuses_a_warm_result(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    scope = OriginalPreparationReads(value.service)
    scope.read(prepared.artifact_id)
    value.artifacts.invalidate(value.request.annual.artifact_id)
    with pytest.raises(SnapshotError, match="metadata changed"):
        scope.read(prepared.artifact_id)
    with pytest.raises(SnapshotError, match="metadata changed"):
        scope.verify()
    scope.clear()


@pytest.mark.parametrize("target", ("source", "receipt"))
def test_content_corruption_before_output_boundary_refuses(
    tmp_path, monkeypatch, target
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    scope = OriginalPreparationReads(value.service)
    _, validations = scope.read(prepared.artifact_id)
    if target == "source":
        source = validations[0].responses[0]
        value.acquisition.content_store._path(
            source.content_hash, source.media_type
        ).write_bytes(b"corrupt")
    else:
        read = value.artifacts.read
        monkeypatch.setattr(
            value.artifacts,
            "read",
            lambda key: b"{}" if key == value.request.annual.artifact_id else read(key),
        )
    with pytest.raises(SnapshotError):
        scope.verify()
    scope.clear()
    # A new operation never inherits the earlier verified result.
    with pytest.raises(SnapshotError):
        OriginalPreparationReads(value.service).read(prepared.artifact_id)


@pytest.mark.parametrize("limits", ({"max_entries": 0}, {"max_retained_bytes": 1}))
def test_unretained_preparation_still_fully_validates(tmp_path, monkeypatch, limits):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    scope = OriginalPreparationReads(value.service, **limits)
    assert scope.read(prepared.artifact_id) == scope.read(prepared.artifact_id)
    assert not scope.entries and scope.retained_bytes == 0
    scope.finish()


def test_eviction_and_independent_scopes_revalidate(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    scope = OriginalPreparationReads(value.service, max_entries=1)
    first = scope.read(prepared.artifact_id)
    different, _ = execute(
        value,
        value.request.model_copy(
            update={"ticker": value.expected_identity.security_id}
        ),
    )
    assert different.artifact_id != prepared.artifact_id
    scope.read(different.artifact_id)
    assert list(scope.entries) == [different.artifact_id]
    assert scope.read(prepared.artifact_id) == first
    assert list(scope.entries) == [prepared.artifact_id]
    assert scope.retained_bytes <= scope.max_retained_bytes
    independent = OriginalPreparationReads(value.service)
    assert independent.read(prepared.artifact_id) == first
    assert (
        independent.entries[prepared.artifact_id]
        is not scope.entries[prepared.artifact_id]
    )
    scope.finish()
    independent.finish()


def test_acquisition_operation_is_nested_independent_and_cleared(tmp_path, monkeypatch):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    acquisition = value.acquisition
    with acquisition.evidence_operation():
        outer = acquisition._original_reads.get()
        expected = outer.read(prepared.artifact_id)
        with acquisition.evidence_operation():
            inner = acquisition._original_reads.get()
            assert inner is not outer
            assert inner.read(prepared.artifact_id) == expected
        assert inner.closed and acquisition._original_reads.get() is outer
    assert outer.closed and acquisition._original_reads.get() is None
    with pytest.raises(ValueError, match="interrupted"):
        with acquisition.evidence_operation():
            failed = acquisition._original_reads.get()
            failed.read(prepared.artifact_id)
            raise ValueError("interrupted")
    assert failed.closed and not failed.entries
    assert acquisition._original_reads.get() is None


def test_mutable_returned_headers_cannot_change_the_retained_handle(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    scope = OriginalPreparationReads(value.service)
    first, validations = scope.read(prepared.artifact_id)
    original_report = validations[0].original.report
    first.request.runtime.taxonomy_version = "changed"
    validations[0].original.source.cik = "9999999999"
    later, checked = scope.read(prepared.artifact_id)
    assert later.request.runtime.taxonomy_version != "changed"
    assert checked[0].original.source.cik != "9999999999"
    assert checked[0].original.report is original_report
    scope.finish()


@pytest.mark.parametrize(
    "limits", ({"max_entries": 0}, {"max_retained_bytes": 1}, {"max_entries": 1})
)
def test_evicted_or_unretained_consumed_evidence_is_checked_at_publication(
    tmp_path, monkeypatch, limits
):
    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    scope = OriginalPreparationReads(value.service, **limits)
    scope.read(prepared.artifact_id)
    different, _ = execute(
        value,
        value.request.model_copy(
            update={"ticker": value.expected_identity.security_id}
        ),
    )
    scope.read(different.artifact_id)
    assert prepared.artifact_id not in scope.entries
    value.artifacts.invalidate(prepared.artifact_id)
    with pytest.raises(SnapshotError, match="metadata changed"):
        scope.verify()
    scope.clear()
    assert scope._journal.closed


def test_revocation_during_later_content_read_refuses_all_consumed_evidence(
    tmp_path, monkeypatch
):
    value = case(tmp_path, monkeypatch)
    first, _ = execute(value)
    second, _ = execute(
        value,
        value.request.model_copy(
            update={"ticker": value.expected_identity.security_id}
        ),
    )
    scope = OriginalPreparationReads(value.service)
    scope.read(first.artifact_id)
    scope.read(second.artifact_id)
    read = value.artifacts.read

    def while_reading_later(key):
        raw = read(key)
        if key == second.artifact_id:
            value.artifacts.invalidate(first.artifact_id)
        return raw

    monkeypatch.setattr(value.artifacts, "read", while_reading_later)
    with pytest.raises(SnapshotError, match="metadata changed"):
        scope.verify()
    scope.clear()
