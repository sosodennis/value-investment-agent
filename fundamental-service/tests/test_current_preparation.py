from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from fundamental_service.current_preparation import (
    CurrentSourcePreparation,
    CurrentSourcePreparationRequestV1,
)
from fundamental_service.preparation_runner import SOURCE_PREPARATION_PLAN
from fundamental_service.public_acquisition import PublicSourceCutoffV1
from fundamental_service.snapshots import SnapshotError
from test_preparation_runner import (
    VALUATION_TIME,
    _fixture,
    _reader,
    _run,
    _runner,
)
from test_public_acquisition import Provider, acquisition, file_lock, inventory, request


def current_fixture(tmp_path, *, artifacts=None):
    baseline = _fixture(tmp_path / "baseline")
    requested_at = VALUATION_TIME - timedelta(seconds=2)
    source_request = request(valuation_timestamp=requested_at)
    template = SOURCE_PREPARATION_PLAN.validate_python(
        {
            **baseline.plan.model_dump(),
            "ingestions": tuple(
                {**item.model_dump(), "valuation_timestamp": requested_at}
                for item in baseline.plan.ingestions
            ),
            "public_sources": (source_request,),
        }
    )
    provider = Provider()
    provider.source = replace(
        provider.source, captured_at=VALUATION_TIME, available_at=VALUATION_TIME
    )
    artifacts = artifacts or baseline.artifacts
    public = acquisition(tmp_path / "public", provider, artifacts=artifacts)

    def selector(
        *, clock=lambda: VALUATION_TIME + timedelta(seconds=1), store=artifacts
    ):
        return CurrentSourcePreparation(
            acquisitions=public,
            artifacts=store,
            selection_lock=lambda key: file_lock(tmp_path / "selection-locks", key),
            clock=clock,
        )

    return SimpleNamespace(
        baseline=baseline,
        provider=provider,
        public=public,
        request=CurrentSourcePreparationRequestV1(template=template),
        selector=selector,
        artifacts=artifacts,
        deadline_at=VALUATION_TIME + timedelta(minutes=10),
    )


def select(fixture, **kwargs):
    return fixture.selector(**kwargs).execute(
        fixture.request, deadline_at=fixture.deadline_at
    )


def test_current_freezes_after_capture_and_formal_composer_still_requires_exact_approval(
    tmp_path,
):
    from fundamental_service.contracts import CallerApprovalEnvelopeV1

    fixture = current_fixture(tmp_path)
    selected, first = select(fixture)
    plan = selected.plan
    assert first.wrote and not selected.issue_codes
    assert plan.ingestions[0].valuation_timestamp == VALUATION_TIME
    assert plan.public_sources == fixture.request.template.public_sources
    assert plan.public_source_cutoff.requested_at == fixture.request.requested_at
    assert selected.captures[0].issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
    assert not selected.captures[0].issues_at(VALUATION_TIME)
    assert fixture.selector().read(first.artifact.artifact_id) == selected

    runner = _runner(fixture.baseline, public_acquisition=fixture.public)
    waiting = _reader(fixture.baseline, _run(runner, plan))
    assert waiting.status == "approval_required" and waiting.calculation is None
    assert waiting.public_source_cutoff == plan.public_source_cutoff
    approval = CallerApprovalEnvelopeV1(
        caller_id="operator",
        decision="approved",
        input_digest=waiting.preparation.input.input_digest,
        decided_at=VALUATION_TIME,
    )
    calculated = _run(runner, plan, approval=approval)
    report = _reader(fixture.baseline, calculated)
    assert report.status == "calculated"
    assert report.preparation.input.input_digest == approval.input_digest
    assert report.public_source_outcomes == selected.captures
    before = inventory(tmp_path)
    repeated = _run(runner, plan, approval=approval)
    assert not repeated.wrote and repeated.artifact == calculated.artifact
    assert inventory(tmp_path) == before and len(fixture.provider.calls) == 1
    with pytest.raises(ValueError, match="different valuation input"):
        _run(
            runner,
            plan,
            approval=approval.model_copy(update={"input_digest": "0" * 64}),
        )


def test_historical_template_keeps_cutoff_and_late_original_refusal(tmp_path):
    fixture = current_fixture(tmp_path)
    report = _reader(
        fixture.baseline,
        _run(
            _runner(fixture.baseline, public_acquisition=fixture.public),
            fixture.request.template,
        ),
    )
    assert report.status == "blocked"
    assert report.issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
    assert report.public_source_cutoff is None
    selected, _ = select(fixture)
    assert selected.plan.ingestions[0].valuation_timestamp == VALUATION_TIME
    assert len(fixture.provider.calls) == 1


@pytest.mark.parametrize("offset", [timedelta(minutes=16), -timedelta(seconds=3)])
def test_new_current_request_rejects_stale_or_future_timestamp_before_io(
    tmp_path, offset
):
    fixture = current_fixture(tmp_path)
    now = fixture.request.requested_at + offset
    with pytest.raises(SnapshotError) as failure:
        fixture.selector(clock=lambda: now).execute(
            fixture.request, deadline_at=now + timedelta(minutes=1)
        )
    assert failure.value.code == "CURRENT_REQUEST_TIME_INVALID"
    assert not fixture.provider.calls


def test_saved_selection_reopens_days_later_without_retiming_or_writes(tmp_path):
    fixture = current_fixture(tmp_path)
    original, first = select(fixture)
    before = inventory(tmp_path)
    later = VALUATION_TIME + timedelta(days=7)
    repeated, second = fixture.selector(clock=lambda: later).execute(
        fixture.request, deadline_at=later + timedelta(minutes=1)
    )
    assert (
        original == repeated and first.artifact == second.artifact and not second.wrote
    )
    assert inventory(tmp_path) == before and len(fixture.provider.calls) == 1
    with pytest.raises(SnapshotError) as failure:
        fixture.selector(clock=lambda: later).execute(
            fixture.request, deadline_at=later
        )
    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert inventory(tmp_path) == before


def test_current_concurrency_selects_one_plan_and_downloads_once(tmp_path):
    fixture = current_fixture(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: select(fixture), range(2)))
    assert outcomes[0][0] == outcomes[1][0]
    assert sorted(publication.wrote for _, publication in outcomes) == [False, True]
    assert len(fixture.provider.calls) == 1


@pytest.mark.parametrize("retryable", [False, True])
def test_source_failure_retained_and_only_transient_failure_can_retry(
    tmp_path, retryable
):
    fixture = current_fixture(tmp_path)
    fixture.provider.error = SnapshotError(
        "SOURCE_RATE_LIMITED", "fixture", retryable=retryable
    )
    failed, first = select(fixture)
    assert failed.plan is None and failed.issue_codes == ("SOURCE_RATE_LIMITED",)
    assert failed.retryable is retryable
    assert fixture.selector().read(first.artifact.artifact_id) == failed
    fixture.provider.error = None
    repeated, second = select(fixture)
    assert fixture.selector().read(first.artifact.artifact_id) == failed
    if retryable:
        assert repeated.plan is not None and second.wrote
        assert len(fixture.provider.calls) == 2
    else:
        assert repeated == failed and not second.wrote
        assert len(fixture.provider.calls) == 1


@pytest.mark.parametrize(
    "stage",
    [
        "current-source-request:",
        "source-preparation-plan:",
        "current-source-preparation:",
    ],
)
def test_crash_after_each_publication_resumes_same_capture_and_plan(tmp_path, stage):
    fixture = current_fixture(tmp_path)

    class Interrupted:
        get = fixture.artifacts.get
        read = fixture.artifacts.read

        def put_with_receipt(self, artifact_id, value, dependency_hashes=()):
            receipt = fixture.artifacts.put_with_receipt(
                artifact_id, value, dependency_hashes
            )
            if artifact_id.startswith(stage):
                raise RuntimeError("interrupted after commit")
            return receipt

    with pytest.raises(RuntimeError, match="interrupted after commit"):
        select(fixture, store=Interrupted())
    later = VALUATION_TIME + timedelta(days=2)
    selected, publication = fixture.selector(clock=lambda: later).execute(
        fixture.request, deadline_at=later + timedelta(minutes=1)
    )
    assert selected.plan.ingestions[0].valuation_timestamp == VALUATION_TIME
    assert fixture.selector().read(publication.artifact.artifact_id) == selected
    assert len(fixture.provider.calls) == 1
    assert not select(fixture)[1].wrote


def test_interrupted_partial_capture_can_retry_without_redownloading_successes(
    tmp_path,
):
    fixture = current_fixture(tmp_path)
    second = fixture.request.template.public_sources[0].model_copy(
        update={"source_profile": "alternative-profile"}
    )
    template = SOURCE_PREPARATION_PLAN.validate_python(
        {
            **fixture.request.template.model_dump(),
            "public_sources": (*fixture.request.template.public_sources, second),
        }
    )
    current = CurrentSourcePreparationRequestV1(template=template)
    original = fixture.public.execute

    def interrupted(request):
        if request == second:
            raise RuntimeError("interrupt before second capture")
        return original(request)

    fixture.public.execute = interrupted
    with pytest.raises(RuntimeError, match="interrupt before second capture"):
        fixture.selector().execute(current, deadline_at=fixture.deadline_at)
    fixture.public.execute = original
    selected, first = fixture.selector().execute(
        current, deadline_at=fixture.deadline_at
    )
    assert selected.plan is not None and len(selected.captures) == 2
    assert len(fixture.provider.calls) == 2
    before = inventory(tmp_path)
    assert (
        not fixture.selector()
        .execute(current, deadline_at=fixture.deadline_at)[1]
        .wrote
    )
    assert fixture.selector().read(first.artifact.artifact_id) == selected
    assert inventory(tmp_path) == before and len(fixture.provider.calls) == 2


@pytest.mark.parametrize("location", ["selection", "request", "plan", "capture"])
def test_corrupt_dependency_fails_without_repair_or_download(tmp_path, location):
    fixture = current_fixture(tmp_path)
    selected, publication = select(fixture)
    artifact_id = {
        "selection": publication.artifact.artifact_id,
        "request": f"current-source-request:{fixture.request.digest}",
        "plan": f"source-preparation-plan:{selected.plan.digest}",
        "capture": selected.captures[0].artifact_id,
    }[location]
    record = fixture.artifacts.get(artifact_id)
    fixture.artifacts._artifact_path(
        record.content_hash, record.media_type
    ).write_bytes(b"corrupt")
    before = inventory(tmp_path)
    with pytest.raises(SnapshotError):
        select(fixture)
    assert inventory(tmp_path) == before and len(fixture.provider.calls) == 1


def test_cutoff_contract_rejects_old_captures_and_changed_plan_dates(tmp_path):
    fixture = current_fixture(tmp_path)
    selected, _ = select(fixture)
    with pytest.raises(ValueError, match="successful recent captures"):
        PublicSourceCutoffV1.model_validate(
            {
                **selected.plan.public_source_cutoff.model_dump(),
                "requested_at": VALUATION_TIME - timedelta(days=1),
            }
        )
    with pytest.raises(ValueError, match="complete plan captures and date"):
        SOURCE_PREPARATION_PLAN.validate_python(
            {
                **selected.plan.model_dump(),
                "ingestions": fixture.request.template.ingestions,
            }
        )


def test_retained_selection_rechecks_current_provider_register(tmp_path):
    fixture = current_fixture(tmp_path)
    select(fixture)
    before = inventory(tmp_path)

    def refuse(*_args):
        raise SnapshotError("SOURCE_REGISTRATION_MISMATCH", "removed source")

    fixture.provider.validate_capture = refuse
    with pytest.raises(SnapshotError) as failure:
        select(fixture)
    assert failure.value.code == "SOURCE_REGISTRATION_MISMATCH"
    assert inventory(tmp_path) == before and len(fixture.provider.calls) == 1


def test_current_cutoff_rebinds_admission_without_rewriting_original_late_evidence(
    tmp_path,
):
    from fundamental_service.current_preparation import CurrentSourcePreparation
    from test_public_admission import admission_fixture

    fixture = current_fixture(tmp_path)
    admitted = admission_fixture(
        tmp_path / "admission",
        at=fixture.request.requested_at,
        artifacts=fixture.artifacts,
    )
    for uri, original in admitted.capture.sources.items():
        admitted.capture.sources[uri] = replace(
            original, captured_at=VALUATION_TIME, available_at=VALUATION_TIME
        )
    template = SOURCE_PREPARATION_PLAN.validate_python(
        {
            **fixture.request.template.model_dump(),
            "public_sources": admitted.requests,
            "source_admissions": (admitted.request,),
        }
    )
    selector = CurrentSourcePreparation(
        acquisitions=admitted.acquisition,
        artifacts=fixture.artifacts,
        selection_lock=lambda key: file_lock(tmp_path / "locks", key),
        clock=lambda: VALUATION_TIME + timedelta(seconds=1),
    )
    selected, _ = selector.execute(
        CurrentSourcePreparationRequestV1(template=template),
        deadline_at=fixture.deadline_at,
    )
    assert len(selected.captures) == 2
    assert all(
        item.issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
        for item in selected.captures
    )
    historical, _ = admitted.service.execute(admitted.request, selected.captures)
    assert historical.issue_codes == ("SOURCE_NOT_AVAILABLE_AT_VALUATION",)
    current, first = admitted.service.execute(
        selected.plan.source_admissions[0], selected.captures
    )
    assert current.admission.status == "admitted" and not current.issue_codes
    assert selected.plan.source_admissions[0].valuation_at == VALUATION_TIME
    assert historical.request.digest != current.request.digest
    assert historical.acquisition_refs == current.acquisition_refs
    before = inventory(tmp_path)
    _, second = admitted.service.execute(
        selected.plan.source_admissions[0], selected.captures
    )
    assert not second.wrote and second.artifact == first.artifact
    assert inventory(tmp_path) == before and len(admitted.capture.calls) == 2


@pytest.mark.parametrize("offset", [-timedelta(hours=1), timedelta(hours=1)])
def test_out_of_window_capture_is_retained_without_a_frozen_plan(tmp_path, offset):
    fixture = current_fixture(tmp_path)
    fixture.provider.source = replace(
        fixture.provider.source,
        captured_at=VALUATION_TIME + offset,
        available_at=VALUATION_TIME + offset,
    )
    selected, first = select(fixture)
    assert selected.plan is None
    assert selected.issue_codes == ("CURRENT_CAPTURE_TIME_INVALID",)
    before = inventory(tmp_path)
    assert not select(fixture)[1].wrote and inventory(tmp_path) == before
    assert fixture.selector().read(first.artifact.artifact_id) == selected


@pytest.mark.parametrize("invalid", ["actor", "approval"])
def test_current_command_rejects_invalid_caller_before_source_or_runtime_access(
    tmp_path, capsys, invalid
):
    from fundamental_service.contracts import CallerApprovalEnvelopeV1
    from fundamental_service.preparation_runner import main
    from fundamental_service.serialization import canonical_bytes

    fixture = current_fixture(tmp_path)
    path = tmp_path / "plan.json"
    path.write_bytes(canonical_bytes(fixture.request.template))
    args = [
        "--current",
        "--plan",
        str(path),
        "--plan-digest",
        fixture.request.template.digest,
        "--actor",
        " " if invalid == "actor" else "operator",
        "--organization",
        "operators",
    ]
    if invalid == "approval":
        approval = tmp_path / "approval.json"
        approval.write_bytes(
            canonical_bytes(
                CallerApprovalEnvelopeV1(
                    caller_id="different-caller",
                    decision="approved",
                    input_digest="a" * 64,
                    decided_at=VALUATION_TIME,
                )
            )
        )
        args.extend(("--approval", str(approval)))
    assert main(args) == 2
    error = capsys.readouterr().err
    assert (
        "actor and organization" if invalid == "actor" else "authenticated subject"
    ) in error
    assert not fixture.provider.calls


def test_postgres_selection_reopens_and_restores_into_empty_store(
    tmp_path, recovery_databases
):
    import asyncio
    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        PostgresMetadataStore,
    )
    from fundamental_service.persistence_recovery import export_backup, restore_backup
    from fundamental_service.public_acquisition import (
        PostgresPublicCaptureLock,
        PublicSourceAcquisition,
    )
    from fundamental_service.serialization import canonical_bytes

    fixture = current_fixture(tmp_path / "setup")
    source_database, target_database = recovery_databases

    def wire(database, root):
        metadata = PostgresMetadataStore(database, auto_migrate=True)
        metadata.start()
        content = PostgresContentStore(root, metadata)
        artifacts = PostgresArtifactStore(metadata, content)
        public = PublicSourceAcquisition(
            provider=fixture.provider,
            artifacts=artifacts,
            content=content,
            capture_lock=PostgresPublicCaptureLock(metadata),
        )
        selector = CurrentSourcePreparation(
            acquisitions=public,
            artifacts=artifacts,
            selection_lock=PostgresPublicCaptureLock(metadata),
            clock=lambda: VALUATION_TIME + timedelta(seconds=1),
        )
        return metadata, selector

    root = tmp_path / "content"
    metadata, selector = wire(source_database, root)
    try:
        selected, first = selector.execute(
            fixture.request, deadline_at=fixture.deadline_at
        )
    finally:
        metadata.close()
    metadata, selector = wire(source_database, root)
    try:
        before = inventory(root)
        repeated, second = selector.execute(
            fixture.request, deadline_at=fixture.deadline_at
        )
        assert (
            repeated == selected
            and first.artifact == second.artifact
            and not second.wrote
        )
        assert inventory(root) == before and len(fixture.provider.calls) == 1
        backup = asyncio.run(
            export_backup(
                source_database,
                root,
                tmp_path / "backups",
                source_revision=fixture.request.template.source_revision,
            )
        )
    finally:
        metadata.close()
    restored_root = tmp_path / "restored"
    asyncio.run(
        restore_backup(
            target_database,
            restored_root,
            tmp_path / "backups" / backup.manifest_digest,
            manifest_digest=backup.manifest_digest,
        )
    )
    metadata, selector = wire(target_database, restored_root)
    try:
        before = inventory(restored_root)
        repeated, second = selector.execute(
            fixture.request, deadline_at=fixture.deadline_at
        )
        assert canonical_bytes(repeated) == canonical_bytes(selected)
        assert second.artifact == first.artifact and not second.wrote
        assert inventory(restored_root) == before and len(fixture.provider.calls) == 1
    finally:
        metadata.close()
