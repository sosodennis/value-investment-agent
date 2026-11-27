from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_candidate_contracts import (
    FiscalPrepareCandidateCommandV2,
    FiscalPreparedCorrectnessV1,
)
from fundamental_service.fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalClosureReadBudget,
    _CLOSURE_BUDGET,
    bound_fiscal_closure_value,
    fiscal_closure_read_operation,
    read_fiscal_artifact_bytes,
)
from fundamental_service.fiscal_validation_contracts import FiscalRetainedInputBindingV1
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError


def reference(role="fiscal-discovery"):
    return ArtifactRefV1(
        artifact_id="fixture:" + role,
        role=role,
        content_hash="1" * 64,
        media_type="application/json",
    )


def test_command_v2_has_a_distinct_locator_from_the_retained_v1_identity():
    command = FiscalPrepareCandidateCommandV2(
        command_id="same-human-command",
        discovery_ref=reference(),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert command.locator_digest != sha256_digest(
        ("fundamental.prepare-fiscal-candidate.v1", command.command_id)
    )
    assert (
        command.artifact_id("fiscal-statement-candidate-v3")
        != "fiscal-statement-candidate-v2:" + command.locator_digest
    )
    with pytest.raises(ValidationError):
        FiscalPrepareCandidateCommandV2.model_validate(
            command.model_dump()
            | {"protocol": "fundamental.prepare-fiscal-candidate.v1"}
        )


@pytest.mark.parametrize(
    "mutation", ["missing_origin", "unknown_origin", "missing_basis_source"]
)
def test_retained_input_contract_refuses_incomplete_or_unknown_origins(mutation):
    origin = {
        "kind": "normalized",
        "integrity_role": "normalized_content",
        "content": {"digest": "2" * 64, "media_type": "text/html", "byte_length": 10},
    }
    staged = {"relative_name": "filing.htm", "origin": origin}
    payload = {
        "source_validation_ref": reference("fiscal-original-validation").model_dump(),
        "source_contract_digest": "3" * 64,
        "inputs": [
            {
                "representation": "normalized",
                "action_result_ref": reference(
                    "sec-parser-action-result-v2"
                ).model_dump(),
                "files": [staged],
            }
        ],
    }
    if mutation == "missing_origin":
        del staged["origin"]
    elif mutation == "unknown_origin":
        origin["kind"] = "unclassified_transform"
    else:
        del payload["source_validation_ref"]
    with pytest.raises(ValidationError):
        FiscalRetainedInputBindingV1.model_validate(payload)


def test_correctness_refuses_unknown_owner_and_duplicate_owner_use_path():
    owner = {
        "owner": "mapping",
        "use_path": "source/0",
        "root_ref": reference().model_dump(),
        "contract_digest": "a" * 64,
        "executable_digest": "b" * 64,
        "policy_digest": "c" * 64,
        "input_footprint_digest": "d" * 64,
    }
    payload = {
        "candidate_content_digest": "e" * 64,
        "closure_contract_digest": "f" * 64,
        "owners": [owner, owner],
    }
    with pytest.raises(ValidationError):
        FiscalPreparedCorrectnessV1.model_validate(payload)
    with pytest.raises(ValidationError):
        FiscalPreparedCorrectnessV1.model_validate(
            payload | {"owners": [owner | {"owner": "unowned"}]}
        )


def test_bounded_artifact_read_checks_full_bytes_and_refuses_overflow(tmp_path):
    store = ArtifactStore(tmp_path)
    payload = b'{"exact":"bytes"}'
    store.put_bytes_with_receipt("fixture", payload, media_type="application/json")
    assert store.read_bounded("fixture", maximum_bytes=len(payload)) == payload
    with pytest.raises(SnapshotError, match="bound"):
        store.read_bounded("fixture", maximum_bytes=len(payload) - 1)
    record = store.get("fixture")
    store._artifact_path(record.content_hash, record.media_type).write_bytes(
        b"x" * len(payload)
    )
    with pytest.raises(SnapshotError, match="differ"):
        store.read_bounded("fixture", maximum_bytes=len(payload))


def test_absence_can_only_transition_through_this_invocations_actual_own_receipt(
    tmp_path,
):
    store = ArtifactStore(tmp_path)
    reader = FiscalArtifactRead(store, lambda: 1.0)
    reader.expect("owned", reader.current("owned"))
    own = store.put_with_receipt("owned", {"value": 1})
    reader.accept_own_publication(own, canonical_bytes({"value": 1}))
    reader.check_bodies()
    assert reader.input_footprint_digest
    foreign = FiscalArtifactRead(store, lambda: 1.0)
    foreign.expect("foreign", None)
    store.put_with_receipt("foreign", {"value": 2})
    duplicate = store.put_with_receipt("foreign", {"value": 2})
    with pytest.raises(SnapshotError, match="own write"):
        foreign.accept_own_publication(duplicate, canonical_bytes({"value": 2}))
    with pytest.raises(SnapshotError, match="metadata changed"):
        foreign.check_current()


def test_nested_canonical_reads_accept_five_plus_four_within_the_operation_bound(
    tmp_path,
):
    store = ArtifactStore(tmp_path)
    store.put_bytes_with_receipt(
        "one", b"x" * (5 * 1024 * 1024), media_type="application/json"
    )
    store.put_bytes_with_receipt(
        "two", b"y" * (4 * 1024 * 1024), media_type="application/json"
    )
    with fiscal_closure_read_operation():
        reader = FiscalArtifactRead(store, lambda: 1.0)
        assert len(reader.read("one")) == 5 * 1024 * 1024
        with fiscal_closure_read_operation():
            assert len(reader.for_consumer().read("two")) == 4 * 1024 * 1024
        reader.check_bodies()


def test_nested_canonical_bodies_metadata_and_footprints_share_32_mib():
    with fiscal_closure_read_operation():
        budget = _CLOSURE_BUDGET.get()
        assert budget is not None
        for index in range(4):
            budget.consume(("body", str(index)), 7 * 1024 * 1024)
        budget.consume(("metadata", "retained"), 3 * 1024 * 1024)
        with fiscal_closure_read_operation():
            bound_fiscal_closure_value(("owner",), "x" * (1024 * 1024 - 2))
            with pytest.raises(SnapshotError, match="bound"):
                bound_fiscal_closure_value(("overflow",), None)


@pytest.mark.parametrize("remaining", [None, 32 * 1024 * 1024, 1024 * 1024])
def test_derived_read_refuses_registered_overflow_before_body_read(remaining):
    from contextlib import nullcontext

    class RegisteredPort:
        def read(self, identity):
            raise AssertionError("derived reads must always be bounded")

        def read_bounded(self, identity, *, maximum_bytes):
            assert identity == "oversized"
            assert maximum_bytes == (
                1024 * 1024 if remaining == 1024 * 1024 else 8 * 1024 * 1024
            )
            raise SnapshotError(
                "FISCAL_CLOSURE_LIMIT", "registered derived body exceeds read bound"
            )

    operation = (
        fiscal_closure_read_operation() if remaining is not None else nullcontext()
    )
    with operation:
        if remaining is not None:
            budget = _CLOSURE_BUDGET.get()
            assert budget is not None
            budget.consume(("canonical", "already-read"), 32 * 1024 * 1024 - remaining)
        with pytest.raises(SnapshotError, match="registered derived body"):
            read_fiscal_artifact_bytes(RegisteredPort(), "oversized")


def test_derived_body_limit_cannot_be_bypassed_by_direct_budget_consumption():
    budget = FiscalClosureReadBudget()
    budget.consume(("body", "within"), 8 * 1024 * 1024)
    with pytest.raises(SnapshotError, match="bound"):
        budget.consume(("body", "oversized"), 8 * 1024 * 1024 + 1)


def test_aggregate_entry_limit_includes_each_distinct_owner_footprint():
    budget = FiscalClosureReadBudget()
    for index in range(4096):
        budget.consume(("owner", str(index)), 0)
    with pytest.raises(SnapshotError, match="bound"):
        budget.consume(("owner", "extra"), 0)


@pytest.mark.parametrize("length", [None, 100])
def test_registered_bounded_content_refuses_before_reading_bytes_and_never_repairs(
    tmp_path, length
):
    from fundamental_service.metadata import PostgresContentStore

    class Metadata:
        def content_byte_length(self, digest, *, media_type):
            if length is None:
                raise SnapshotError(
                    "CONTENT_REGISTRATION_UNAVAILABLE", "registration missing"
                )
            return length

        def register_content(self, *args, **kwargs):
            raise AssertionError("bounded read must not repair registration")

    class Filesystem:
        def get_bounded(self, *args, **kwargs):
            raise AssertionError("rejected registration must not read bytes")

    root = tmp_path / "content"
    root.mkdir()
    store = PostgresContentStore(root, Metadata(), read_only=True)
    store._filesystem_view = Filesystem()
    with pytest.raises(SnapshotError):
        store.get_bounded("a" * 64, media_type="application/json", maximum_bytes=10)


def test_current_records_refuses_first_mismatch_before_decoding_later_bad_record(
    tmp_path,
):
    from types import SimpleNamespace

    from fundamental_service.data_releases import DataReleaseError
    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        _RetainedArtifactMetadata,
    )

    record = ArtifactStore(tmp_path / "artifacts").put("first", {"value": 1})
    entries = {
        "first": _RetainedArtifactMetadata(
            canonical_bytes(record.model_copy(update={"status": "invalidated"})), 11
        ),
        "later": _RetainedArtifactMetadata(b"not-json", 0),
    }
    metadata = SimpleNamespace(retained_artifact_records=lambda ids: entries)
    artifacts = PostgresArtifactStore(
        metadata, PostgresContentStore(tmp_path / "content", metadata)
    )
    with pytest.raises(DataReleaseError) as changed:
        artifacts.require_current_records(
            (("first", record), ("later", None)), check_deadline=lambda: None
        )
    assert changed.value.code == "ARTIFACT_EVIDENCE_CHANGED"
    entries["first"] = _RetainedArtifactMetadata(canonical_bytes(record), 11)
    with pytest.raises(ValidationError):
        artifacts.require_current_records(
            (("first", record), ("later", None)), check_deadline=lambda: None
        )


@pytest.mark.parametrize(
    "after_length, expected_code",
    [(None, "CONTENT_REGISTRATION_UNAVAILABLE"), (99, "CONTENT_METADATA_MISMATCH")],
)
def test_bounded_artifact_refuses_registration_before_decoding_after_metadata(
    tmp_path, after_length, expected_code
):
    from types import SimpleNamespace

    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        _BoundedArtifactObservation,
    )

    raw = b'{"value":1}'
    record = ArtifactStore(tmp_path / "artifacts").put("retained", {"value": 1})
    metadata = SimpleNamespace(
        _bounded_artifact_before=lambda identity: _BoundedArtifactObservation(
            canonical_bytes(record), len(raw)
        ),
        _bounded_artifact_after=lambda identity, **pair: _BoundedArtifactObservation(
            b"not-json", after_length
        ),
    )
    content = PostgresContentStore(tmp_path / "content", metadata)
    content._filesystem.put(raw, media_type=record.media_type)
    artifacts = PostgresArtifactStore(metadata, content)
    with pytest.raises(SnapshotError) as refused:
        artifacts.read_bounded(record.artifact_id, maximum_bytes=len(raw))
    assert refused.value.code == expected_code


def test_bounded_artifact_refuses_actual_length_before_after_metadata_lookup(tmp_path):
    from types import SimpleNamespace

    from fundamental_service.metadata import (
        PostgresArtifactStore,
        PostgresContentStore,
        _BoundedArtifactObservation,
    )

    raw = b'{"value":1}'
    record = ArtifactStore(tmp_path / "artifacts").put("retained", {"value": 1})

    def unavailable(*args, **kwargs):
        raise AssertionError("actual length mismatch must refuse before after lookup")

    metadata = SimpleNamespace(
        _bounded_artifact_before=lambda identity: _BoundedArtifactObservation(
            canonical_bytes(record), len(raw) + 1
        ),
        _bounded_artifact_after=unavailable,
    )
    content = PostgresContentStore(tmp_path / "content", metadata)
    content._filesystem.put(raw, media_type=record.media_type)
    artifacts = PostgresArtifactStore(metadata, content)
    with pytest.raises(SnapshotError) as refused:
        artifacts.read_bounded(record.artifact_id, maximum_bytes=len(raw) + 1)
    assert refused.value.code == "CONTENT_METADATA_MISMATCH"


def test_readonly_canary_refuses_missing_configuration_and_retained_network_gaps():
    from fundamental_service.fiscal_release_runtime import (
        FiscalCanaryConfigurationV1,
        _RetainedCanaryAdapter,
    )
    from fundamental_service.sec_source import SecRequestPolicy, SecSourceError

    with pytest.raises(ValidationError):
        FiscalCanaryConfigurationV1.model_validate({"database_role": "reader"})
    adapter = _RetainedCanaryAdapter(
        SecRequestPolicy(user_agent="contract-test test@example.test")
    )
    with pytest.raises(SecSourceError, match="retained source closure"):
        adapter._request(
            "https://www.sec.gov/Archives/edgar/data/1/source.htm",
            deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        )
