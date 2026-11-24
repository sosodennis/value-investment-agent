from dataclasses import replace
from datetime import timedelta

from test_automatic_source_acquisition import acquire
from test_automatic_source_mapping import statement_source_case
from test_original_preparation import case, execute
from fundamental_service.statement_release_builder import build_statement_release
from types import SimpleNamespace


def test_prepared_original_identity_survives_later_submissions_capture(
    tmp_path, monkeypatch
):
    value = case(tmp_path / "source", monkeypatch, statement_original=True)
    delegate = value.acquisition.adapter._request

    def independent_capture_times(uri, *, deadline_at=None):
        response = delegate(uri, deadline_at=deadline_at)
        offset = 600 if "/submissions/" in uri else 0
        return replace(
            response, available_at=response.available_at + timedelta(seconds=offset)
        )

    monkeypatch.setattr(
        value.acquisition.adapter, "_request", independent_capture_times
    )
    prepared, _ = execute(value)
    original_ref = value.service.reference(
        prepared.artifact_id, "sec-original-preparation-v1"
    )
    request, *_ = statement_source_case(tmp_path / "request", monkeypatch)
    request = request.model_copy(update={"original_preparation": original_ref})
    ingestion = acquire(request, value.acquisition)
    build_statement_release(
        original_ref,
        (ingestion,),
        originals=value.service,
        snapshots=SimpleNamespace(get=lambda key: value.metadata.snapshots[key]),
        facts=SimpleNamespace(get=lambda key: value.metadata.facts[key]),
        mappings=SimpleNamespace(get_mapping=lambda key: value.metadata.mappings[key]),
        artifacts=value.artifacts,
        source_revision=request.source_revision,
        mapping_version=request.mapping_version,
    )
