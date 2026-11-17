"""Parser reuse preserves exact dependencies, original time and live validity."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest

from fundamental_service.arelle_parser import (
    ArelleParseReportV1,
    ArelleParserError,
    ArelleValidationProfileV1,
)
from fundamental_service.metadata import IngestionLockLease
from fundamental_service.parser_action_contracts import ParserActionInputV1
from fundamental_service.parser_action_evidence import require_parser_action_evidence
from fundamental_service.parser_action_identity import _files, _runtime_tree
from fundamental_service.parser_actions import (
    ParserActions,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError


class Index:
    parser_action_reuse_configured = True

    def __init__(self):
        self.results, self.locks, self.held = {}, {}, {}
        self.guard = Lock()

    def try_acquire_ingestion_lock(self, key):
        with self.guard:
            lock = self.locks.setdefault(key, Lock())
            if not lock.acquire(blocking=False):
                return None
            lease = IngestionLockLease(key, 0)
            self.held[lease.lease_id] = lock
            return lease

    def release_ingestion_lock(self, lease):
        with self.guard:
            self.held.pop(lease.lease_id).release()

    def parser_action_result(self, key):
        return self.results.get(key)

    def publish_parser_action_result(self, key, artifact_id):
        self.results[key] = artifact_id


def case(tmp_path):
    profile = ArelleValidationProfileV1(
        profile_id="sec-efm-us-dqc-v31.0.3",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path("/edgar"),
        xule_plugin_dir=Path("/xule"),
        dqc_ruleset_path=Path("/rules.zip"),
        edgar_plugin_sha256="a" * 64,
        xule_plugin_sha256="b" * 64,
        dqc_ruleset_sha256="c" * 64,
    )
    request = ParserActionInputV1(
        delivery_revision="d" * 40,
        representation="normalized",
        entrypoint="filing.htm",
        files=(("filing.htm", "1" * 64),),
        normalization_inputs=("2" * 64,),
        implementation_digest="3" * 64,
        runtime_digest="4" * 64,
        resources=(("taxonomy", "5" * 64),),
        profile_digest=profile.digest(),
        taxonomy_version="2025",
        source_content_hash="1" * 64,
        output_schema_digest="6" * 64,
    )
    artifacts, content, index = (
        ArtifactStore(tmp_path / "artifacts"),
        FilesystemContentStore(tmp_path / "content"),
        Index(),
    )
    owner = ParserActions(index=index, artifacts=artifacts)
    calls = []

    def execute():
        calls.append(True)
        return ArelleParseReportV1(
            filing_path="/original/staging/filing.htm",
            parser_version=profile.arelle_version,
            taxonomy_version=request.taxonomy_version,
            validation_profile=profile,
            validation_profile_digest=profile.digest(),
            parsed_at=datetime.now(UTC),
            source_content_hash=request.source_content_hash,
            taxonomy_cache_hash="5" * 64,
            validation_engines=("sec-efm", "dqc-us"),
            validation_evidence=(
                "strict-sec-efm-profile-selected",
                "dqc-dqcrt-checks-completed",
            ),
        )

    def run(**changes):
        arguments = dict(
            request=request,
            profile=profile,
            deadline_at=datetime.now(UTC) + timedelta(seconds=10),
            execute=execute,
            check_inputs=lambda: request,
        )
        arguments.update(changes)
        return owner._perform(**arguments)

    return SimpleNamespace(**locals())


def issuer(c, report):
    from test_original_issuer import original
    from fundamental_service.original_issuer import evaluate_original_issuer

    _, source = original()
    source = source.model_copy(
        update={"parser_input_hash": c.request.source_content_hash}
    )
    return evaluate_original_issuer(
        report, source=source, decision_at=datetime.now(UTC)
    )


def test_reuse_survives_new_owner_without_changing_body_or_parsed_time(tmp_path):
    c = case(tmp_path)
    first = c.run()
    c.owner = ParserActions(index=c.index, artifacts=c.artifacts)
    second = c.owner._perform(
        request=c.request,
        profile=c.profile,
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
        execute=c.execute,
        check_inputs=lambda: c.request,
    )
    assert canonical_bytes(first.model_dump(mode="json")) == canonical_bytes(
        second.model_dump(mode="json")
    )
    assert (
        first.parsed_at == second.parsed_at and first.filing_path == second.filing_path
    )
    assert len(c.calls) == 1 and len(c.index.results) == 1
    assert not c.index.held


@pytest.mark.parametrize(
    "field",
    (
        "files",
        "normalization_inputs",
        "implementation_digest",
        "runtime_digest",
        "resources",
        "profile_digest",
        "taxonomy_version",
        "source_content_hash",
        "output_schema_digest",
        "delivery_revision",
        "representation",
    ),
)
def test_every_declared_dependency_changes_the_action_key(tmp_path, field):
    c = case(tmp_path)
    value = getattr(c.request, field)
    replacement = {
        "files": (("filing.htm", "7" * 64),),
        "normalization_inputs": ("7" * 64,),
        "resources": (("taxonomy", "7" * 64),),
        "representation": "archive",
    }.get(field, "e" * len(value))
    assert c.request.model_copy(update={field: replacement}).digest != c.request.digest


@pytest.mark.parametrize(
    "failure",
    (
        "report_missing",
        "report_corrupt",
        "result_corrupt",
        "result_invalid",
        "wrong_pointer",
    ),
)
def test_broken_cache_is_reparsed_without_mutating_retained_evidence(
    tmp_path, monkeypatch, failure
):
    c = case(tmp_path)
    first = c.run()
    original_id = c.index.results[c.request.digest]
    record = c.artifacts.get(original_id)
    if failure in {"report_missing", "report_corrupt"}:
        from fundamental_service.parser_action_contracts import ParserActionResultV1

        result = ParserActionResultV1.model_validate_json(c.artifacts.read(original_id))
        path = c.artifacts._artifact_path(
            result.report_content_hash, "application/json"
        )
        if failure == "report_missing":
            path.unlink()
        else:
            path.write_bytes(b"corrupt")
    elif failure == "result_invalid":
        c.artifacts.invalidate(original_id)
    elif failure == "wrong_pointer":
        c.index.results[c.request.digest] = "unknown-result"
    else:
        c.artifacts._artifact_path(record.content_hash, record.media_type).write_bytes(
            b"corrupt"
        )
    second = c.run()
    assert len(c.calls) == 2 and second.parsed_at >= first.parsed_at
    assert c.index.results[c.request.digest] != original_id
    assert not c.index.held


def test_current_revocation_during_slow_dependency_check_refuses_reuse(tmp_path):
    c = case(tmp_path)
    c.run()

    def revoke():
        c.artifacts.invalidate(c.index.results[c.request.digest])
        return c.request

    with pytest.raises(SnapshotError, match="result differs"):
        c.run(check_inputs=revoke)
    assert len(c.calls) == 1 and not c.index.held


def test_changed_input_during_parse_never_publishes_a_reusable_result(tmp_path):
    c = case(tmp_path)
    changed = c.request.model_copy(update={"runtime_digest": "e" * 64})
    with pytest.raises(SnapshotError, match="dependencies changed"):
        c.run(check_inputs=lambda: changed)
    assert not c.index.results and not c.index.held


def test_deadline_expiring_during_hit_check_refuses_output(tmp_path):
    c = case(tmp_path)
    c.run()
    deadline = datetime.now(UTC) + timedelta(milliseconds=25)

    def expire():
        import time

        time.sleep(0.04)
        return c.request

    with pytest.raises(ArelleParserError, match="deadline expired"):
        c.run(deadline_at=deadline, check_inputs=expire)


def test_interrupted_attempt_can_resume_and_retains_start_and_failure(tmp_path):
    c = case(tmp_path)

    def interrupted():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        c.run(execute=interrupted)
    assert not c.index.results and not c.index.held
    assert c.run().parsed_at and len(c.calls) == 1
    c.artifacts._load_records(force=True)
    ids = tuple(c.artifacts._records)
    assert sum(":failed" in key for key in ids) == 1


def test_exact_key_contenders_execute_one_parser_body(tmp_path):
    c = case(tmp_path)
    with ThreadPoolExecutor(max_workers=3) as pool:
        reports = tuple(pool.map(lambda _: c.run(), range(3)))
    assert len(c.calls) == 1
    assert (
        len({canonical_bytes(report.model_dump(mode="json")) for report in reports})
        == 1
    )
    assert not c.index.held


def test_staged_tree_hashes_all_bytes_and_does_not_follow_unknown_links(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    path = root / "custom-definition.xml"
    path.write_text("first")
    before = _files(root)
    path.write_text("other")
    assert before != _files(root)
    (root / "link").symlink_to(path)
    with pytest.raises(ValueError, match="symlinked"):
        _files(root)


def test_independent_consumer_verifies_the_retained_body_and_current_metadata(tmp_path):
    c = case(tmp_path)
    report = c.run()
    arguments = dict(
        artifacts=c.artifacts,
        delivery_revision=c.request.delivery_revision,
    )
    require_parser_action_evidence(issuer(c, report), **arguments)
    changed = issuer(c, report)
    changed = changed.model_copy(
        update={
            "report": changed.report.model_copy(update={"filing_path": "/another-path"})
        }
    )
    with pytest.raises(SnapshotError, match="normalized report differs"):
        require_parser_action_evidence(changed, **arguments)
    c.artifacts.invalidate(c.index.results[c.request.digest])
    with pytest.raises(SnapshotError, match="action (result )?differs"):
        require_parser_action_evidence(issuer(c, report), **arguments)


def test_independent_consumer_rejects_a_different_delivery(tmp_path):
    c = case(tmp_path)
    report = c.run()
    with pytest.raises(SnapshotError, match="action (result )?differs"):
        require_parser_action_evidence(
            issuer(c, report), artifacts=c.artifacts, delivery_revision="e" * 40
        )


def test_native_runtime_link_hashes_target_content_and_refuses_cycles(tmp_path):
    target = tmp_path / "library.so"
    target.write_bytes(b"one")
    link = tmp_path / "symlink.so"
    link.symlink_to(target)
    before = _runtime_tree(link, set(), {})
    target.write_bytes(b"two")
    assert _runtime_tree(link, set(), {}) != before
    (tmp_path / "cycle").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="cyclic"):
        _runtime_tree(tmp_path, set(), {})


@pytest.mark.parametrize("searchable", (True, False))
def test_unlistable_runtime_requires_proven_search_denial(
    tmp_path, monkeypatch, searchable
):
    from fundamental_service.parser_action_identity import IncompleteParserClosure

    directory = tmp_path / "private"
    directory.mkdir()
    (directory / "known.cfg").write_bytes(b"dependency")
    iterdir = Path.iterdir

    def denied(path):
        if path == directory:
            raise PermissionError()
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", denied)
    monkeypatch.setattr(
        "fundamental_service.parser_action_identity.os.access",
        lambda *a, **k: searchable,
    )
    if searchable:
        with pytest.raises(IncompleteParserClosure, match="cannot be enumerated"):
            _runtime_tree(directory, set(), {})
    else:
        assert _runtime_tree(directory, set(), {})
    with pytest.raises(PermissionError):
        _files(tmp_path)


def test_fresh_mapping_verifier_tracks_action_result_and_report_revocation(tmp_path):
    from fundamental_service.automatic_mapping_evidence import (
        AutomaticMappingEvidenceChecks,
    )
    from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError

    c = case(tmp_path)
    original = issuer(c, c.run())
    closure = require_parser_action_evidence(
        original,
        artifacts=c.artifacts,
        delivery_revision=c.request.delivery_revision,
    )
    refs = tuple(
        ArtifactRefV1(
            artifact_id=identity,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role="sec-parser-action-report-v1"
            if identity.startswith("sec-parser-action-report-v1:")
            else "sec-parser-action-result-v1",
        )
        for identity, record in closure
    )
    request = SimpleNamespace(
        original=original,
        source_revision=c.request.delivery_revision,
        evidence_refs=refs,
    )
    checks = AutomaticMappingEvidenceChecks()
    checks.require_parser_actions(request, artifacts=c.artifacts)
    c.artifacts.invalidate(closure[0][0])
    with pytest.raises((SnapshotError, DataReleaseError)):
        AutomaticMappingEvidenceChecks().require_parser_actions(
            request, artifacts=c.artifacts
        )
    with pytest.raises((SnapshotError, DataReleaseError)):
        checks.require_parser_actions(request, artifacts=c.artifacts)


def test_issuer_normalization_retains_raw_parser_time_and_rejects_report_replacement(
    tmp_path,
):
    c = case(tmp_path)
    report = c.run()
    original = issuer(c, report)
    assert original.report.validation_profile.edgar_plugin_dir == Path("edgar")
    assert original.report.filing_path != report.filing_path
    assert original.report.parsed_at != report.parsed_at
    require_parser_action_evidence(
        original,
        artifacts=c.artifacts,
        delivery_revision=c.request.delivery_revision,
    )
    from fundamental_service.original_issuer import evaluate_original_issuer

    changed = evaluate_original_issuer(
        report.model_copy(
            update={
                "validation_evidence": (*report.validation_evidence, "altered-evidence")
            }
        ),
        source=original.source,
        decision_at=original.decision_at,
    )
    with pytest.raises(SnapshotError, match="normalized report differs"):
        require_parser_action_evidence(
            changed,
            artifacts=c.artifacts,
            delivery_revision=c.request.delivery_revision,
        )


def test_original_preparation_reads_verify_real_issuer_transformation(
    tmp_path, monkeypatch
):
    import fundamental_service.ingestion as ingestion
    import fundamental_service.parser_actions as actions
    from test_original_preparation import case as preparation_case, execute
    from fundamental_service.original_preparation import OriginalPreparationReads

    value = preparation_case(tmp_path / "preparation", monkeypatch)
    prototype = case(tmp_path / "action")

    def identity(path, **kwargs):
        return prototype.request.model_copy(
            update={
                "delivery_revision": kwargs["delivery_revision"],
                "representation": kwargs["representation"],
                "source_content_hash": kwargs["source_content_hash"],
                "files": ((path.name, kwargs["source_content_hash"]),),
                "entrypoint": path.name,
                "profile_digest": kwargs["profile"].digest(),
                "taxonomy_version": kwargs["taxonomy_version"],
                "resources": (
                    ("taxonomy", value.acquisition.settings.taxonomy_cache_sha256),
                ),
            }
        )

    monkeypatch.setattr(actions, "parser_action_input", identity)
    monkeypatch.setattr(actions, "parse_filing_offline", ingestion.parse_filing_offline)
    index = Index()
    value.acquisition.ingestion.parser_actions = ParserActions(
        index=index, artifacts=value.artifacts
    )
    prepared, _ = execute(value)
    validation_id = prepared.filings[0].validation.artifact_id
    evidence = value.service.read_validation(validation_id)
    assert evidence.original.status == "matched" and index.results
    scope = OriginalPreparationReads(value.service)
    scope.read(prepared.artifact_id)
    value.artifacts.invalidate(next(iter(index.results.values())))
    with pytest.raises(SnapshotError):
        value.service.read_validation(validation_id)
    with pytest.raises(SnapshotError):
        scope.verify()
    scope.clear()


def test_archive_comparison_uses_same_filing_date_applicability(tmp_path):
    from datetime import date
    from fundamental_service.arelle_parser import ArelleFindingV1
    from fundamental_service.dqc_applicability import (
        DqcFilingContextV1,
        dqc_applicability_policy_digest,
    )
    from fundamental_service.regulatory_validation import bind_dqc_filing_context

    c = case(tmp_path)
    execute = c.execute
    profile = c.profile.model_copy(
        update={"dqc_applicability_digest": dqc_applicability_policy_digest()}
    )
    request = c.request.model_copy(update={"profile_digest": profile.digest()})

    def with_future_rule():
        return execute().model_copy(
            update={
                "validation_profile": profile,
                "validation_profile_digest": profile.digest(),
                "findings": (
                    ArelleFindingV1(
                        code="DQC.US.0243.10944",
                        severity="warning",
                        rule_severity="error",
                        message="official rule effective after filing date",
                    ),
                ),
            }
        )

    normalized = c.run(
        execute=with_future_rule,
        request=request,
        profile=profile,
        check_inputs=lambda: request,
    )
    archive_request = request.model_copy(update={"representation": "archive"})
    archive = c.run(
        request=archive_request,
        check_inputs=lambda: archive_request,
        execute=with_future_rule,
        profile=profile,
    )
    context = DqcFilingContextV1(
        issuer_id="0000000001",
        accession_number="0000000001-26-000001",
        filing_date=date(2026, 2, 1),
        policy_digest=dqc_applicability_policy_digest(),
    )
    report = bind_dqc_filing_context(normalized, context)
    assert not report.blocking_finding_codes()
    report = report.model_copy(
        update={
            "validation_evidence": (
                *report.validation_evidence,
                archive.validation_evidence[-1],
            )
        }
    )
    require_parser_action_evidence(
        issuer(c, report),
        artifacts=c.artifacts,
        delivery_revision=c.request.delivery_revision,
    )


def test_mapping_signer_rechecks_consumed_action_after_evaluation(
    tmp_path, monkeypatch
):
    import fundamental_service.automatic_mapping_runner as runner
    from fundamental_service.data_releases import ArtifactRefV1, DataReleaseError
    from test_automatic_mapping import case as mapping_case, approve

    request, store, roots, _ = mapping_case(tmp_path)
    record = store.put_with_receipt(
        "consumed-action-body", {"retained": "body"}
    ).artifact
    ref = ArtifactRefV1(
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
        role="sec-parser-action-report-v1",
    )
    request = request.model_copy(
        update={"evidence_refs": (*request.evidence_refs, ref)}
    )
    evaluate = runner.evaluate_automatic_mapping

    def revoke(*args, **kwargs):
        decision = evaluate(*args, **kwargs)
        assert decision.status == "approved"
        store.invalidate(record.artifact_id)
        return decision

    monkeypatch.setattr(runner, "evaluate_automatic_mapping", revoke)
    with pytest.raises((SnapshotError, DataReleaseError)):
        approve(request, store, roots)
    assert not any(
        key.startswith("automatic-mapping-approval-") for key in store._records
    )


@pytest.mark.parametrize("stage", ("canary", "candidate"))
def test_release_signer_rechecks_action_after_final_publication(
    tmp_path, monkeypatch, stage
):
    from fundamental_service.automatic_data_release import AutomaticDataReleaseService
    from fundamental_service.data_releases import ArtifactRefV1
    from test_automatic_data_release import _case

    _, store, request, options = _case(tmp_path)
    record = store.put_with_receipt(
        "consumed-action-body", {"retained": "body"}
    ).artifact
    ref = ArtifactRefV1(
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
        role="sec-parser-action-report-v1",
    )
    request = request.model_copy(
        update={
            "content": request.content.model_copy(
                update={
                    "evidence_refs": (*request.content.evidence_refs, ref),
                }
            )
        }
    )
    put = store.put_with_receipt
    seen = []

    def revoke(identity, *args, **kwargs):
        publication = put(identity, *args, **kwargs)
        if identity.startswith(f"automatic-release-{stage}-"):
            seen.append(identity)
            store.invalidate(record.artifact_id)
        return publication

    monkeypatch.setattr(store, "put_with_receipt", revoke)
    receipt = AutomaticDataReleaseService(**options).verify_and_sign(request)
    assert seen and receipt.decision.status == "blocked"
    assert receipt.candidate_publication is None
    if stage == "candidate":
        assert any(
            identity.startswith("automatic-release-rejected-candidate-")
            for identity in store._records
        )


def test_final_action_check_hashes_uncached_bytes_after_evaluation(
    tmp_path, monkeypatch
):
    from fundamental_service.automatic_mapping_evidence import (
        AutomaticMappingEvidenceChecks,
    )
    from fundamental_service.parser_action_evidence import (
        require_current_parser_action_refs,
    )
    from fundamental_service.data_releases import ArtifactRefV1

    c = case(tmp_path)
    report = c.run()
    refs = tuple(
        ArtifactRefV1(
            artifact_id=identity,
            content_hash=record.content_hash,
            media_type=record.media_type,
            role="sec-parser-action-report-v1"
            if identity.startswith("sec-parser-action-report-v1:")
            else "sec-parser-action-result-v1",
        )
        for identity, record in require_parser_action_evidence(
            issuer(c, report),
            artifacts=c.artifacts,
            delivery_revision=c.request.delivery_revision,
        )
    )
    checks = AutomaticMappingEvidenceChecks(max_retained_bytes=0)
    reader = checks.reader(c.artifacts)
    request = SimpleNamespace(
        original=issuer(c, report),
        source_revision=c.request.delivery_revision,
        evidence_refs=refs,
    )
    checks.require_parser_actions(request, artifacts=reader)
    read = c.artifacts.read
    monkeypatch.setattr(
        c.artifacts,
        "read",
        lambda identity: b"corrupt"
        if identity == refs[0].artifact_id
        else read(identity),
    )
    with pytest.raises(SnapshotError, match="action bytes changed"):
        require_current_parser_action_refs(refs, artifacts=reader)


def test_public_owner_falls_back_when_dependency_closure_is_unknown(
    tmp_path, monkeypatch
):
    import fundamental_service.parser_actions as actions
    from fundamental_service.parser_action_identity import IncompleteParserClosure

    c = case(tmp_path)

    def unknown(*args, **kwargs):
        raise IncompleteParserClosure("unaccounted dependency")

    monkeypatch.setattr(actions, "parser_action_input", unknown)
    monkeypatch.setattr(
        actions, "parse_filing_offline", lambda *args, **kwargs: c.execute()
    )
    report = c.owner.parse(
        tmp_path / "filing.htm",
        representation="normalized",
        delivery_revision="d" * 40,
        normalization_inputs=("2" * 64,),
        profile=c.profile,
        taxonomy_version="2025",
        taxonomy_cache_dir=tmp_path,
        source_content_hash="1" * 64,
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )
    assert report.parsed_at and len(c.calls) == 1 and not c.index.results
    assert not any(
        value.startswith("sec-parser-action-v1:")
        for value in report.validation_evidence
    )


def test_owner_composed_before_metadata_start_uses_current_capability(
    tmp_path, monkeypatch
):
    import fundamental_service.parser_actions as actions

    c = case(tmp_path)
    c.index.parser_action_reuse_configured = False
    owner = actions.postgres_parser_actions(c.index, c.artifacts)
    monkeypatch.setattr(actions, "parser_action_input", lambda *a, **k: c.request)
    monkeypatch.setattr(actions, "parse_filing_offline", lambda *a, **k: c.execute())
    arguments = dict(
        representation="normalized",
        delivery_revision=c.request.delivery_revision,
        normalization_inputs=c.request.normalization_inputs,
        profile=c.profile,
        taxonomy_version=c.request.taxonomy_version,
        taxonomy_cache_dir=tmp_path,
        source_content_hash=c.request.source_content_hash,
        deadline_at=datetime.now(UTC) + timedelta(seconds=10),
    )
    first = owner.parse(tmp_path / "filing.htm", **arguments)
    assert not c.index.results and not any(
        v.startswith("sec-parser-action-v1:") for v in first.validation_evidence
    )
    c.index.parser_action_reuse_configured = True
    second = owner.parse(tmp_path / "filing.htm", **arguments)
    third = owner.parse(tmp_path / "filing.htm", **arguments)
    assert second == third and len(c.calls) == 2 and c.index.results


def test_postgres_single_flight_restart_and_empty_store_restore(
    recovery_databases, tmp_path
):
    import asyncio
    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        PostgresMetadataStore,
    )
    from fundamental_service.persistence_recovery import export_backup, restore_backup

    source_db, target_db = recovery_databases
    c = case(tmp_path)
    root = tmp_path / "pg-content"
    metadata = PostgresMetadataStore(source_db, auto_migrate=True)
    metadata.start()

    def run(store, content_root):
        content = PostgresContentStore(content_root, store)
        artifacts = PostgresArtifactStore(store, content)
        owner = ParserActions(index=store, artifacts=artifacts)
        return owner._perform(
            request=c.request,
            profile=c.profile,
            deadline_at=datetime.now(UTC) + timedelta(seconds=10),
            execute=c.execute,
            check_inputs=lambda: c.request,
        )

    try:
        assert metadata.parser_action_reuse_configured
        with ThreadPoolExecutor(max_workers=3) as pool:
            reports = tuple(pool.map(lambda _: run(metadata, root), range(3)))
        assert len(c.calls) == 1
        assert all(report == reports[0] for report in reports)
        pointer = metadata.parser_action_result(c.request.digest)
    finally:
        metadata.close()
    reopened = PostgresMetadataStore(source_db)
    reopened.start()
    try:
        assert run(reopened, root) == reports[0]
        assert reopened.parser_action_result(c.request.digest) == pointer
        assert len(c.calls) == 1
    finally:
        reopened.close()
    backups = tmp_path / "backups"
    backup = asyncio.run(
        export_backup(source_db, root, backups, source_revision="d" * 40)
    )
    restored_root = tmp_path / "restored"
    asyncio.run(
        restore_backup(
            target_db,
            restored_root,
            backups / backup.manifest_digest,
            manifest_digest=backup.manifest_digest,
        )
    )
    restored = PostgresMetadataStore(target_db)
    restored.start()
    try:
        assert restored.parser_action_result(c.request.digest) == pointer
        assert run(restored, restored_root) == reports[0] and len(c.calls) == 1
    finally:
        restored.close()


@pytest.mark.parametrize(
    "limits", ({}, {"max_reports": 0}, {"max_report_bytes": 0}, {"max_reports": 1})
)
@pytest.mark.parametrize(
    "field", ("input_digest", "output_digest", "status", "decision_at", "source")
)
def test_checked_claim_reuse_rejects_forged_headers_even_after_eviction(
    tmp_path, limits, field
):
    from fundamental_service.original_issuer import OriginalIssuerEvidenceChecks

    c = case(tmp_path)
    original = issuer(c, c.run())
    checks = OriginalIssuerEvidenceChecks(**limits)
    arguments = dict(
        artifacts=c.artifacts,
        delivery_revision=c.request.delivery_revision,
        original_checks=checks,
    )
    require_parser_action_evidence(original, **arguments)
    if limits.get("max_reports") == 1:
        other = issuer(
            c,
            c.execute().model_copy(update={"validation_evidence": ("different-body",)}),
        )
        checks.validate(other)
    changed = {
        "input_digest": "0" * 64,
        "output_digest": "0" * 64,
        "status": "matched" if original.status == "refused" else "refused",
        "decision_at": original.decision_at + timedelta(seconds=1),
        "source": original.source.model_copy(
            update={"uri": original.source.uri + "changed"}
        ),
    }[field]
    with pytest.raises(SnapshotError, match="normalized report differs"):
        require_parser_action_evidence(
            original.model_copy(update={field: changed}), **arguments
        )
    require_parser_action_evidence(original, **arguments)


@pytest.mark.parametrize("field", ("decision_at", "source"))
def test_claim_cache_rejects_same_json_but_unvalidated_header_type(tmp_path, field):
    from fundamental_service.original_issuer import OriginalIssuerEvidenceChecks

    c = case(tmp_path)
    original = issuer(c, c.run())
    checks = OriginalIssuerEvidenceChecks()
    arguments = dict(
        artifacts=c.artifacts,
        delivery_revision=c.request.delivery_revision,
        original_checks=checks,
    )
    require_parser_action_evidence(original, **arguments)
    replacement = original.model_dump(mode="json")[field]
    if field == "source":
        replacement = original.source.model_copy(
            update={"captured_at": replacement["captured_at"]}
        )
    forged = original.model_copy(update={field: replacement})
    with pytest.raises(SnapshotError, match="normalized report differs"):
        require_parser_action_evidence(forged, **arguments)


def test_report_equivalence_requires_exact_canonical_values(tmp_path):
    from fundamental_service.original_issuer import _issuer_input_digest
    from fundamental_service.serialization import sha256_digest

    c = case(tmp_path)
    original = issuer(c, c.run())
    changed_report = original.report.model_copy(update={"offline": 1})
    assert (
        changed_report == original.report
    )  # Python bool/int equality is insufficient.
    forged = original.model_copy(
        update={
            "report": changed_report,
            "input_digest": _issuer_input_digest(
                original.source, original.decision_at, changed_report
            ),
        }
    )
    forged = forged.model_copy(
        update={
            "output_digest": sha256_digest(forged.model_dump(exclude={"output_digest"}))
        }
    )
    with pytest.raises(SnapshotError, match="normalized report differs"):
        require_parser_action_evidence(
            forged, artifacts=c.artifacts, delivery_revision=c.request.delivery_revision
        )
