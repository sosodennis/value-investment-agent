from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import fundamental_service.fiscal_candidate_preparation as preparation
import fundamental_service.metadata as metadata_module
import fundamental_service.parser_action_identity as resource_identity
import pytest
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_admission_history import FiscalControlBindingV1
from fundamental_service.metadata import PostgresArtifactStore
from fundamental_service.replay import ArtifactRecordV1
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import SnapshotError


@pytest.fixture
def candidate_scope(monkeypatch):
    trace = []
    state = SimpleNamespace(
        now=datetime(2026, 1, 1, tzinfo=UTC),
        active=None,
        scopes=0,
        failure=None,
        expire=False,
        deadline=False,
        cleanup_failure=False,
    )
    record = ArtifactRecordV1(artifact_id="candidate", content_hash="a" * 64)
    reference = ArtifactRefV1(
        role="fiscal-statement-candidate-v3",
        **record.model_dump(include={"artifact_id", "content_hash", "media_type"}),
    )
    command = SimpleNamespace(
        expires_at=state.now + timedelta(minutes=2),
        locator_digest="b" * 64,
        command_digest="c" * 64,
        artifact_id=lambda role: role,
    )
    execution = SimpleNamespace(
        authority_id="preparer",
        principal_id="machine",
        principal_kind="machine",
        key_id="key",
        grant_ref=reference,
        execution_id="job",
        started_at=state.now,
        completed_at=state.now,
    )
    signed = SimpleNamespace(
        body=SimpleNamespace(
            command=command,
            content="content",
            correctness="correctness",
            preparation=execution,
            issuance=SimpleNamespace(origin_id="origin"),
            signed_at=state.now,
        )
    )
    materialized = SimpleNamespace(
        content="content",
        correctness="correctness",
        consumed_metadata=(),
        source_evidence=(),
        content_readsets=(),
        artifact_readset=(),
        projection="projection",
        source_documents=(),
    )

    def require_scope(stage):
        assert state.active is not None
        trace.append((state.active, stage))

    class Read:
        records = ((record.artifact_id, record),)
        readset = ()

        def __init__(self, artifacts, budget):
            require_scope("reader")

        def enroll(self, readset):
            pass

        def expect(self, identity, expected):
            pass

        def get(self, identity):
            require_scope("get")
            return record

        def check_bodies(self):
            require_scope("bodies")

        def check_current(self):
            require_scope("fresh_records")

    @contextmanager
    def read_operation():
        assert state.active is None
        state.scopes += 1
        state.active = identity = state.scopes
        trace.append((identity, "open"))

        def seal():
            require_scope("seal")
            if state.failure == "seal":
                raise failure
            if state.expire:
                state.now = command.expires_at
            if state.deadline:
                state.now = deadline_at

        try:
            yield seal
        finally:
            trace.append((identity, "reset"))
            state.active = None

    class Materialization:
        def current(self):
            require_scope("materialization_current")
            if state.failure == "materialization":
                raise failure
            return materialized

    @contextmanager
    def materialization(trusted, *, deadline_at):
        require_scope("materialization_open")
        try:
            yield Materialization()
        finally:
            trace.append((state.active, "children_close"))
            if state.cleanup_failure:
                raise RuntimeError("child cleanup")

    seal_resources = resource_identity._ParserResourceCut.seal
    close_resources = resource_identity._CurrentParserResourceOperation.__exit__

    def resources_seal(cut):
        require_scope("resources_finish")
        return seal_resources(cut)

    def resources_close(operation, *args):
        trace.append((state.active, "resources_close"))
        return close_resources(operation, *args)

    monkeypatch.setattr(resource_identity._ParserResourceCut, "seal", resources_seal)
    monkeypatch.setattr(
        resource_identity._CurrentParserResourceOperation, "__exit__", resources_close
    )

    authority = SimpleNamespace(
        history_heads=(),
        grant_ref=reference,
        grant=SimpleNamespace(valid_until=command.expires_at),
        observed_at=state.now,
    )
    epoch = SimpleNamespace(
        require_current_issuance=lambda issuance: None,
        require_current_activity=lambda *times: None,
    )
    control = SimpleNamespace(
        entries=(
            SimpleNamespace(
                event=SimpleNamespace(
                    body=FiscalControlBindingV1(
                        action="candidate_prepared",
                        payload_ref=reference,
                        command_digest=command.command_digest,
                    ),
                    origin_id="origin",
                    recorded_at=state.now,
                )
            ),
        ),
        heads=(),
        require_current_epoch=lambda entries: None,
    )

    def history_finish(*args, **kwargs):
        require_scope("history")
        if state.failure == "history":
            raise failure
        return SimpleNamespace(entries=(), heads=(), observed_through=state.now)

    def configuration():
        require_scope("configuration")
        return "generation"

    def intent(*args):
        require_scope("intent")
        return "intent"

    monkeypatch.setattr(preparation, "FiscalArtifactRead", Read)
    monkeypatch.setattr(
        preparation, "FiscalCandidateSigningIntentV2", lambda **kw: "marker"
    )
    monkeypatch.setattr(
        preparation,
        "read_retained_artifact",
        lambda reader, ref: canonical_bytes(
            "intent" if ref.role == "fiscal-candidate-intent-v2" else "marker"
        ),
    )
    owner = preparation.FiscalCandidatePreparation(
        builder=SimpleNamespace(_open_current_materialization=materialization),
        artifacts=object(),
        read_artifacts=object(),
        history=SimpleNamespace(
            read_epoch=lambda **kw: epoch,
            read=lambda *args, **kw: control,
            finish_observation=history_finish,
        ),
        authorities=object(),
        authority_id="preparer",
        configuration_digest=configuration,
        clock=lambda: state.now,
        read_operation=read_operation,
    )
    monkeypatch.setattr(owner, "_load", lambda *args: signed)
    monkeypatch.setattr(owner, "_authority", lambda *args: authority)
    monkeypatch.setattr(owner, "_intent", intent)
    monkeypatch.setattr(owner, "_dependencies", lambda *args: ())
    deadline_at = state.now + timedelta(minutes=1)
    failure = SnapshotError("SYNC_SCOPE_FAILURE", "fixed scope failure")
    operation = preparation.FiscalCandidateOperation(owner, reference, deadline_at)
    return SimpleNamespace(
        owner=owner,
        operation=operation,
        trace=trace,
        state=state,
        failure=failure,
        deadline_at=deadline_at,
    )


def test_candidate_returns_each_proof_after_its_own_final_cut(candidate_scope):
    case = candidate_scope
    with case.operation as candidate:
        assert case.state.active is None
        assert resource_identity._RESOURCE_OPERATION.get() is None
        candidate.current()
        assert case.state.active is None
        case.trace.extend(
            [(None, "parent_absence"), (None, "parent_write"), (None, "parent_sign")]
        )
    assert case.operation.completed.content == "content"
    assert case.state.active is None
    assert case.state.scopes == 3
    for identity in (1, 2, 3):
        stages = [stage for scope, stage in case.trace if scope == identity]
        assert stages[0] == "open"
        assert stages[-1] == "reset"
        assert stages.index("resources_finish") < stages.index("bodies")
        assert (
            stages.index("fresh_records")
            < stages.index("seal")
            < stages.index("history")
        )
        assert stages.index("history") < len(stages) - 1 - stages[::-1].index(
            "configuration"
        )
        assert stages[stages.index("seal") + 1 :] == [
            "history",
            "configuration",
            "intent",
            "reset",
        ]
    assert case.trace.index((3, "children_close")) < case.trace.index(
        (3, "resources_finish")
    )
    assert case.trace.index((2, "reset")) < case.trace.index((None, "parent_write"))
    assert case.trace.index((None, "parent_sign")) < case.trace.index((3, "open"))


@pytest.mark.parametrize("crossed", ["expire", "deadline"])
def test_candidate_cut_time_cannot_escape_final_expiry_or_budget(
    candidate_scope, crossed
):
    case = candidate_scope
    setattr(case.state, crossed, True)
    with pytest.raises(SnapshotError) as caught:
        with case.operation:
            pytest.fail("expired proof reached its parent")
    assert caught.value.code == (
        "REQUEST_DEADLINE_EXCEEDED"
        if crossed == "deadline"
        else "FISCAL_CANDIDATE_INVALID"
    )
    assert case.state.active is None
    assert preparation._CANDIDATE_OPERATION.get() is None
    assert (None, "resources_close") in case.trace
    assert (None, "children_close") in case.trace


@pytest.mark.parametrize("stage", ["materialization", "seal", "history"])
def test_candidate_failure_keeps_original_error_and_releases_children(
    candidate_scope, stage
):
    case = candidate_scope
    case.state.failure, case.state.cleanup_failure = stage, True
    with pytest.raises(SnapshotError) as caught:
        with case.operation:
            pytest.fail("failed proof reached its parent")
    assert caught.value is case.failure
    assert case.state.active is None
    assert preparation._CANDIDATE_OPERATION.get() is None
    assert (None, "resources_close") in case.trace
    assert (None, "children_close") in case.trace


def test_candidate_rejects_replaced_read_operation(candidate_scope):
    case = candidate_scope
    with pytest.raises(SnapshotError, match="owner changed"):
        with case.operation as candidate:
            case.owner.read_operation = lambda: None
            candidate.current()
    assert preparation._CANDIDATE_OPERATION.get() is None


def test_candidate_cleanup_failure_without_primary_error_is_not_hidden(candidate_scope):
    case = candidate_scope
    with pytest.raises(RuntimeError, match="child cleanup"):
        with case.operation:
            case.state.cleanup_failure = True
    assert case.state.active is None
    assert preparation._CANDIDATE_OPERATION.get() is None
    assert case.operation._session._phase == "failed"


class EmptyMetadata:
    def __init__(self, trace):
        self.trace = trace

    def retained_artifact_records(self, ids):
        self.trace.append(ids)
        return {}


def test_candidate_borrowing_release_outer_scope_leaves_its_cut_to_owner(
    candidate_scope, tmp_path
):
    case = candidate_scope
    cuts = []
    content = SimpleNamespace(_root=tmp_path)
    content.as_read_only = lambda: content
    store = PostgresArtifactStore(EmptyMetadata(cuts), content, read_only=True)
    case.owner.read_operation = store.scoped_read_operation
    operation = preparation.FiscalCandidateOperation(
        case.owner, case.operation._session._reference, case.deadline_at
    )
    case.state.active = "release"
    with store.scoped_read_operation() as outer_cut:
        with operation as candidate:
            candidate.current()
            assert store._scoped_reads() is not None
        assert store._scoped_reads() is not None
        assert cuts == [()]
        outer_cut()
        assert cuts == [(), ()]
    assert metadata_module._SCOPED_ARTIFACT_READS.get() is None
    assert cuts == [(), ()]


def test_owned_cut_borrower_and_closed_callback_keep_metadata_ownership(tmp_path):
    trace = []
    metadata = EmptyMetadata(trace)
    content = SimpleNamespace(_root=tmp_path)
    content.as_read_only = lambda: content
    store = PostgresArtifactStore(metadata, content, read_only=True)
    with store.scoped_read_operation() as seal:
        with store.as_read_only().scoped_read_operation() as borrowed:
            borrowed()
            assert store._scoped_reads() is not None
        assert trace == [()]
        seal()
        assert trace == [(), ()]
        with pytest.raises(RuntimeError, match="ended"):
            store._scoped_reads()
    assert metadata_module._SCOPED_ARTIFACT_READS.get() is None
    assert trace == [(), ()]
    with pytest.raises(RuntimeError, match="ended"):
        seal()
    with store.scoped_read_operation():
        pass
    assert trace == [(), (), (), ()]


@pytest.mark.parametrize("primary", [False, True])
def test_metadata_cleanup_resets_scope_and_preserves_primary_error(
    tmp_path, monkeypatch, primary
):
    metadata = EmptyMetadata([])
    content = SimpleNamespace(_root=tmp_path)
    content.as_read_only = lambda: content
    store = PostgresArtifactStore(metadata, content, read_only=True)
    failure = SnapshotError("SYNC_SCOPE_FAILURE", "fixed scope failure")

    def close(reader):
        raise RuntimeError("reader cleanup")

    monkeypatch.setattr(metadata_module._RetainedPostgresArtifactReads, "close", close)
    with pytest.raises(SnapshotError if primary else RuntimeError) as caught:
        with store.scoped_read_operation() as seal:
            if primary:
                raise failure
            seal()
    if primary:
        assert caught.value is failure
    assert metadata_module._SCOPED_ARTIFACT_READS.get() is None


def test_closed_candidate_first_sample_opens_and_proves_in_one_cut(candidate_scope):
    case = candidate_scope
    session = case.owner._open_display_candidate(
        case.operation._session._reference, deadline_at=case.deadline_at
    )
    assert case.trace == []
    assert session.sample().content == "content"
    assert case.state.scopes == 1
    assert session.sample().content == "content"
    assert session.finish().content == "content"
    assert case.state.scopes == 3
    assert case.trace.index((1, "materialization_open")) < case.trace.index(
        (1, "materialization_current")
    )
    assert case.trace.index((3, "children_close")) < case.trace.index(
        (3, "resources_finish")
    )
    assert preparation._CANDIDATE_OPERATION.get() is None
    assert session.completed.content == "content"
    with pytest.raises(SnapshotError, match="closed"):
        session.sample()


@pytest.mark.parametrize("consumption", ["decision", "terminal"])
@pytest.mark.parametrize("changed", ["materialization", "history", "expire"])
def test_closed_candidate_rechecks_dependencies_at_each_consumption(
    candidate_scope, consumption, changed
):
    case = candidate_scope
    session = case.owner._open_display_candidate(
        case.operation._session._reference, deadline_at=case.deadline_at
    )
    session.sample()
    if consumption == "terminal":
        session.sample()
    if changed == "expire":
        case.state.expire = True
    else:
        case.state.failure = changed
    with pytest.raises(SnapshotError):
        session.finish() if consumption == "terminal" else session.sample()
    assert preparation._CANDIDATE_OPERATION.get() is None
    assert case.state.active is None
    with pytest.raises(SnapshotError, match="did not complete"):
        _ = session.completed


def test_closed_candidate_cleanup_failure_prevents_completion(candidate_scope):
    case = candidate_scope
    session = case.owner._open_display_candidate(
        case.operation._session._reference, deadline_at=case.deadline_at
    )
    session.sample()
    case.state.cleanup_failure = True
    with pytest.raises(RuntimeError, match="child cleanup"):
        session.finish()
    assert preparation._CANDIDATE_OPERATION.get() is None
    with pytest.raises(SnapshotError, match="did not complete"):
        _ = session.completed


@pytest.mark.parametrize("method", ["sample", "finish"])
def test_closed_candidate_foreign_actor_cannot_consume_or_close(
    candidate_scope, monkeypatch, method
):
    case = candidate_scope
    session = case.owner._open_display_candidate(
        case.operation._session._reference, deadline_at=case.deadline_at
    )
    session.sample()
    with monkeypatch.context() as patch:
        patch.setattr(preparation, "_candidate_actor", lambda: ("foreign",))
        with pytest.raises(SnapshotError, match="another execution"):
            getattr(session, method)()
    assert preparation._CANDIDATE_OPERATION.get() is session
    assert session.finish().content == "content"
    assert preparation._CANDIDATE_OPERATION.get() is None


def test_borrowed_candidate_requires_entry_before_current(candidate_scope):
    case = candidate_scope
    with pytest.raises(SnapshotError, match="closed"):
        case.operation.current()
    assert case.trace == []
    with case.operation as read:
        assert read.current().content == "content"
    assert case.operation.completed.content == "content"
