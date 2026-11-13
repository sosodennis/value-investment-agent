"""History arms preserve source policy, labels, refusals, and repeat identity."""

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fundamental_service.contracts import QualityStatus
from fundamental_service.operating_label_contracts import OperatingComparisonRequestV1
from fundamental_service.operating_scenario_contracts import ScenarioPeriodV1
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import replay_history_study_windows as windows  # noqa: E402

pytest_plugins = ("test_history_study_evidence",)


def extend_history(seed, start_year):
    original = seed.decision.source.originals[0]
    added = []
    for year in range(start_year, 2023):
        for fact in original.report.facts:
            if fact.period_start == date(2023, 1, 1) or fact.instant == date(
                2023, 12, 31
            ):
                changes = {
                    name: getattr(fact, name).replace(year=year)
                    for name in ("period_start", "period_end", "instant")
                    if getattr(fact, name) is not None
                }
                changes["context_id"] = f"{fact.context_id}-{year}"
                added.append(fact.model_copy(update=changes))
    report = original.report.model_copy(
        update={"facts": (*original.report.facts, *added)}
    )
    source = compose_issuer_operating_source(
        (
            evaluate_original_issuer(
                report, source=original.source, decision_at=original.decision_at
            ),
        ),
        valuation_timestamp=original.decision_at,
    )
    facts = tuple(
        sorted(
            (
                candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
                for mapping in seed.decision.mappings
                for candidate in parsed_facts_to_candidates(
                    report,
                    source=original.source,
                    issuer_id=original.source.cik,
                    normalized_field=mapping.normalized_field,
                    mapping=mapping,
                )
            ),
            key=lambda fact: fact.fact_id,
        )
    )
    periods = tuple(
        ScenarioPeriodV1(
            fiscal_year=year,
            period_start=date(year, 1, 1),
            period_end=date(year, 12, 31),
            fact_ids={
                fact.normalized_field: fact.fact_id
                for fact in facts
                if fact.period_end.year == year
            },
        )
        for year in range(start_year, 2026)
    )
    scenarios = tuple(
        scenario.model_copy(
            update={
                "continuing_capex_fractions": {
                    **scenario.continuing_capex_fractions,
                    **{year: Decimal(1) for year in range(start_year, 2023)},
                }
            }
        )
        for scenario in seed.decision.scenarios
    )
    decision = seed.decision.model_copy(
        update={
            "source": source,
            "facts": facts,
            "periods": periods,
            "scenarios": scenarios,
        }
    )
    return OperatingComparisonRequestV1.model_validate_json(
        canonical_bytes(
            seed.model_copy(
                update={
                    "decision": decision,
                    "decision_input_digest": sha256_digest(decision),
                }
            )
        )
    )


def seed_index(directory, seed):
    raw = canonical_bytes(seed)
    content_digest = sha256_digest(seed)
    (directory / f"{content_digest}.json").write_bytes(raw)
    return windows.WindowSeedIndex(
        schema_version="history-study-window-seeds.v1",
        fixed_manifest_digest=windows.exporter.MANIFEST_DIGEST,
        runtime=windows.exporter.runtime_pins(),
        seeds=(
            windows.exporter.FileReference(
                path=f"{content_digest}.json", sha256=content_digest
            ),
        ),
    )


@pytest.mark.parametrize(
    "start_year,available", [(2023, [3]), (2022, [3, 4]), (2021, [3, 4, 5])]
)
def test_windows_use_common_sources_labels_and_policy(evidence, start_year, available):
    manifest, _, directory, seed = evidence
    seed = extend_history(seed, start_year)
    before = canonical_bytes(seed)
    output, artifacts = windows.prepare_windows(
        manifest, seed_index(directory, seed), directory
    )
    assert [
        row["years"] for row in output["windows"] if row["status"] != "unavailable"
    ] == available
    assert len(output["windows"]) == 3
    assert (
        output["represented_issuers"] == output["independent_conditional_issuers"] == 1
    )
    assert (
        output["complete_exact_study_cases"] == 0
        and output["supported_history_threshold"] is None
    )
    requests = [
        value
        for value in artifacts.values()
        if value.get("contract_version") == "fundamental.operating-comparison.v1"
    ]
    assert len(requests) == len(available)
    for value in requests:
        request = OperatingComparisonRequestV1.model_validate_json(
            canonical_bytes(value)
        )
        assert request.label == seed.label
        assert request.decision.source == seed.decision.source
        assert request.decision.facts == seed.decision.facts
        assert request.decision.mappings == seed.decision.mappings
        years = {period.fiscal_year for period in request.decision.periods}
        assert all(
            set(s.continuing_capex_fractions) == years
            for s in request.decision.scenarios
        )
    assert any(
        row["model"] == "transition_fcff_dcf" and row["abstained_comparisons"]
        for row in output["arm_summaries"]
    )
    assert canonical_bytes(seed) == before


def test_shorter_window_matches_official_forecast_and_never_synthesizes_older_data(
    evidence,
):
    _, _, _, seed = evidence
    longer = extend_history(seed, 2021)
    short = windows.trailing_request(longer, 3)
    assert [
        row.nodes for row in replay_operating_scenarios(short.decision).results
    ] == [row.nodes for row in replay_operating_scenarios(seed.decision).results]
    with pytest.raises(ValueError, match="unavailable"):
        windows.trailing_request(seed, 4)
    with pytest.raises(ValueError, match="unavailable"):
        windows.trailing_request(longer, 2)


def test_duplicate_issuer_and_runtime_mismatch_fail(evidence):
    manifest, _, directory, seed = evidence
    index = seed_index(directory, seed)
    with pytest.raises(ValueError, match="one longest-history"):
        windows.prepare_windows(
            manifest, index.model_copy(update={"seeds": index.seeds * 2}), directory
        )
    with pytest.raises(ValueError, match="runtime"):
        windows.prepare_windows(
            manifest,
            index.model_copy(
                update={
                    "runtime": index.runtime.model_copy(update={"python": "unknown"})
                }
            ),
            directory,
        )


def test_tampered_and_foreign_evidence_fail_before_output(evidence, monkeypatch):
    manifest, _, directory, seed = evidence
    index = seed_index(directory, seed)
    path = directory / index.seeds[0].path
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="digest mismatch"):
        windows.prepare_windows(manifest, index, directory)
    index = seed_index(directory, seed)
    foreign = json.loads(canonical_bytes(manifest))
    foreign["issuer_decisions"][0]["decision_accession"] = "0000000001-00-000001"
    monkeypatch.setattr(windows.exporter, "MANIFEST_DIGEST", sha256_digest(foreign))
    index = index.model_copy(
        update={"fixed_manifest_digest": windows.exporter.MANIFEST_DIGEST}
    )
    with pytest.raises(ValueError, match="decision accession"):
        windows.prepare_windows(foreign, index, directory)


def test_cli_reuses_identical_artifacts_and_refuses_wrong_commit(
    evidence, monkeypatch, capsys
):
    manifest, _, directory, seed = evidence
    index = seed_index(directory, seed)
    manifest_path, index_path = directory / "manifest.json", directory / "index.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    index_path.write_bytes(canonical_bytes(index))
    output = directory / "output"
    monkeypatch.setattr(
        windows.subprocess,
        "check_output",
        lambda command, **kwargs: "" if "status" in command else "a" * 40,
    )
    command = [
        "replay_history_study_windows.py",
        "--manifest",
        str(manifest_path),
        "--seed-index",
        str(index_path),
        "--exact-commit",
        "a" * 40,
        "--output-directory",
        str(output),
    ]
    monkeypatch.setattr(sys, "argv", command)
    assert windows.main() == 0
    first = json.loads(capsys.readouterr().out)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()}
    assert windows.main() == 0
    second = json.loads(capsys.readouterr().out)
    assert first["wrote"] is True and second["wrote"] is False
    assert {k: v for k, v in first.items() if k != "wrote"} == {
        k: v for k, v in second.items() if k != "wrote"
    }
    assert {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()
    } == before
    command[command.index("--exact-commit") + 1] = "b" * 40
    with pytest.raises(SystemExit) as error:
        windows.main()
    assert error.value.code == 2
    assert {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()
    } == before


def test_interrupted_publication_reuses_completed_artifacts(
    evidence, monkeypatch, capsys
):
    manifest, _, directory, seed = evidence
    index = seed_index(directory, seed)
    manifest_path, index_path = directory / "manifest.json", directory / "index.json"
    manifest_path.write_bytes(canonical_bytes(manifest))
    index_path.write_bytes(canonical_bytes(index))
    output = directory / "output"
    monkeypatch.setattr(
        windows.subprocess,
        "check_output",
        lambda command, **kwargs: "" if "status" in command else "a" * 40,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "replay_history_study_windows.py",
            "--manifest",
            str(manifest_path),
            "--seed-index",
            str(index_path),
            "--exact-commit",
            "a" * 40,
            "--output-directory",
            str(output),
        ],
    )
    publish = windows.publish_report
    calls = 0

    def interrupted(directory, value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated interruption")
        return publish(directory, value)

    monkeypatch.setattr(windows, "publish_report", interrupted)
    with pytest.raises(SystemExit) as error:
        windows.main()
    assert error.value.code == 2
    retained = {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()
    }
    assert len([name for name in retained if name.endswith(".json")]) == 1
    monkeypatch.setattr(windows, "publish_report", publish)
    assert windows.main() == 0
    assert json.loads(capsys.readouterr().out)["wrote"] is True
    assert {
        name: ((output / name).read_bytes(), (output / name).stat().st_mtime_ns)
        for name in retained
    } == retained
    completed = {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()
    }
    assert windows.main() == 0
    assert json.loads(capsys.readouterr().out)["wrote"] is False
    assert {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in output.iterdir()
    } == completed
