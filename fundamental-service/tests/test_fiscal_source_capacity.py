from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from fundamental_service.fiscal_source_closure import (
    FiscalArtifactRead,
    FiscalClosureReadBudget,
    _FiscalSourceArtifactRead,
    fiscal_closure_read_operation,
)
from fundamental_service.replay import ArtifactStore
from fundamental_service.snapshots import SnapshotError
from test_fiscal_discovery import DiscoveryHarness


MIB = 1024 * 1024


def test_source_distinct_capacity_accepts_five_plus_four_and_keeps_one_global_key_set():
    budget = FiscalClosureReadBudget()
    budget._consume_source_body("source-one", "a" * 64, 5 * MIB)
    budget._consume_source_body("source-two", "b" * 64, 4 * MIB)
    budget._consume_source_body("source-one", "a" * 64, 5 * MIB)
    for index in range(4094):
        budget.consume(("canonical", index), 0)
    with pytest.raises(SnapshotError, match="bound"):
        budget.consume(("canonical", "overflow"), 0)


def test_source_distinct_capacity_is_per_operation_and_never_promotes_derived_bytes():
    budget = FiscalClosureReadBudget()
    for index in range(16):
        budget._consume_source_body(str(index), "a" * 64, 16 * MIB)
    assert budget._source_remaining("new-source") == 0
    with pytest.raises(SnapshotError, match="bound"):
        budget._consume_source_body("new-source", "a" * 64, 1)
    assert budget._source_remaining("0") == 16 * MIB
    budget = FiscalClosureReadBudget()
    with pytest.raises(SnapshotError, match="bound"):
        budget._consume_source_body("oversized", "a" * 64, 16 * MIB + 1)
    budget.consume(("body", "derived"), 1)
    with pytest.raises(SnapshotError, match="cannot acquire"):
        budget._source_remaining("derived")
    budget._consume_source_body("source", "a" * 64, 1)
    with pytest.raises(SnapshotError, match="bound"):
        budget.consume(("body", "source"), 1)
    with pytest.raises(SnapshotError, match="commitment changed"):
        budget._consume_source_body("source", "b" * 64, 1)


@pytest.mark.parametrize("used", [0, 255 * MIB])
def test_source_preflight_refuses_registered_overflow_before_returning_body(
    tmp_path, used
):
    store = ArtifactStore(tmp_path)
    record = store.put("source", {"synthetic": "bounded port"})

    class RegisteredPort:
        body_reads = 0

        def get(self, identity):
            assert identity == "source"
            return record

        def require_current_records(self, expected, *, check_deadline):
            store.require_current_records(expected, check_deadline=check_deadline)

        def read_bounded(self, identity, *, maximum_bytes):
            assert maximum_bytes == (MIB if used else 16 * MIB)
            registered_length = maximum_bytes + 1
            if registered_length > maximum_bytes:
                raise SnapshotError(
                    "FISCAL_CLOSURE_LIMIT", "registered source exceeds bound"
                )
            self.body_reads += 1
            raise AssertionError("overflow must refuse before actual body read")

    port = RegisteredPort()
    with fiscal_closure_read_operation():
        reader = _FiscalSourceArtifactRead(port, lambda: None, "source")
        for index in range(15):
            if used:
                reader._source_budget._consume_source_body(
                    str(index), "a" * 64, 16 * MIB
                )
        if used:
            reader._source_budget._consume_source_body("last", "a" * 64, 15 * MIB)
        with pytest.raises(SnapshotError, match="registered source exceeds bound"):
            reader.read("source")
    assert port.body_reads == 0


def test_discovery_source_origins_survive_parent_consumer_and_final_full_body_read(
    tmp_path,
):
    harness = DiscoveryHarness(tmp_path)
    evidence, _ = harness.publish()
    with fiscal_closure_read_operation():
        full = harness.discovery().read_with_inputs(
            evidence.artifact_id, deadline_at=harness.deadline
        )
        current = harness.discovery().read_current_inputs(
            evidence.artifact_id, deadline_at=harness.deadline
        )
        assert full.input_footprint == current.input_footprint
        assert full.artifact_readset.records == current.artifact_readset.records
        assert full.artifact_readset.bodies == current.artifact_readset.bodies
        parent = FiscalArtifactRead(harness.artifacts, lambda: None)
        consumer = parent.for_consumer()
        consumer.enroll(full.artifact_readset)
        assert parent.readset.source_bodies
        assert parent.readset.content_readsets
        assert parent.read(evidence.artifact_id) == consumer.read(evidence.artifact_id)
        assert parent.input_footprint == consumer.input_footprint
        another = parent.for_consumer()
        assert another.records == ()
        another.read(evidence.artifact_id)
        assert len(another.readset.source_bodies) == 1
        parent.check_bodies()
        record = harness.artifacts.get(evidence.artifact_id)
        path = harness.artifacts._artifact_path(record.content_hash, record.media_type)
        body = path.read_bytes()
        path.write_bytes(b"x" * len(body))
        with pytest.raises(SnapshotError):
            parent.check_bodies()


@pytest.mark.parametrize("mutation", ["unknown-protocol", "extra-edge", "fake-type"])
def test_source_owner_refuses_unknown_schema_fake_model_and_extra_edges(
    tmp_path, mutation
):
    harness = DiscoveryHarness(tmp_path)
    evidence, _ = harness.publish()
    with fiscal_closure_read_operation():
        if mutation == "unknown-protocol":
            harness.artifacts.put("unknown", {"protocol": "unowned-source.v999"})
            with pytest.raises(ValidationError):
                harness.discovery().read_current_inputs(
                    "unknown", deadline_at=harness.deadline
                )
        elif mutation == "fake-type":
            reader = _FiscalSourceArtifactRead(
                harness.artifacts, lambda: None, evidence.artifact_id
            )
            with pytest.raises(SnapshotError, match="concrete typed"):
                reader._discovery_edges(
                    SimpleNamespace(request=evidence.request, sources=evidence.sources)
                )
        else:
            harness.artifacts.put(
                "derived-extra",
                {"protocol": "fundamental.fiscal-discovery-evidence.v1"},
            )
            reader = _FiscalSourceArtifactRead(
                harness.artifacts, lambda: None, evidence.artifact_id
            )
            reader._discovery_edges(evidence)
            with pytest.raises(SnapshotError, match="outside the typed source graph"):
                reader.read("derived-extra")


def test_current_source_rejects_action_refs_outside_the_marker_derived_graph(
    tmp_path, monkeypatch
):
    from fundamental_service import fiscal_source_validation as module
    from fundamental_service.data_releases import ArtifactRefV1
    from fundamental_service.fiscal_validation_contracts import (
        ResolvedFiscalValidationRequestV1,
    )
    from test_fiscal_source_closure import SyntheticCompleteSource, _closure, _selection

    harness = DiscoveryHarness(tmp_path)
    discovery, publication = harness.publish()
    source = SyntheticCompleteSource(harness)
    closure = _closure(harness, source)
    request = ResolvedFiscalValidationRequestV1(
        selection=_selection(discovery, publication),
        filing=discovery.selection.selected[0],
        valuation_timestamp=discovery.request.valuation_timestamp,
        pin=closure._pin,
    )
    outcome = source.validate(request, deadline_at=harness.deadline)
    extra = ArtifactRefV1(
        artifact_id="unrelated-derived-body",
        role="sec-parser-action-report-v1",
        content_hash="f" * 64,
        media_type="application/json",
    )
    monkeypatch.setattr(module, "resolve_fiscal_validation_profile", lambda *args: None)
    monkeypatch.setattr(
        module,
        "read_fiscal_parser_actions",
        lambda *args, **kwargs: SimpleNamespace(refs=(*outcome.action_refs, extra)),
    )
    owner = SimpleNamespace(
        settings=SimpleNamespace(
            supported_filing_years=(request.filing.filing_date.year,),
            supported_filing_forms=(request.filing.form,),
        ),
        content_store=harness.content,
    )
    validation = module.SecFiscalSourceValidation(
        owner, pin=request.pin, store=harness.artifacts
    )
    with pytest.raises(SnapshotError, match="current parser action edges differ"):
        validation.observe_current(
            request,
            outcome,
            None,
            artifacts=harness.artifacts,
            deadline_at=harness.deadline,
        )
