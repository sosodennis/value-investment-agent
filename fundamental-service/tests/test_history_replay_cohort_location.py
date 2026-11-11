"""Frozen cohort identity survives relocation independently of package layout."""

from __future__ import annotations

import gzip
import json
import os
import shutil
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from fundamental_service.history_forecast_replay import (
    FIXED_COHORT_DIGEST,
    HistoryReplayPlanV1,
    HistoryReplayService,
    ReplayModelPinV1,
    ReplayOriginV1,
    run_history_replay,
)
from fundamental_service.history_mapping_audit import _filings
from fundamental_service.policies import initial_policy_records
from fundamental_service.serialization import canonical_bytes

COHORT_PATH = Path("docs/acceptance/issue-359-sec-cohort-v1")
PROTOCOL_PATH = Path("docs/acceptance/issue-359-cohort-protocol-v1.json")
SOURCE_ROOT = Path(
    os.environ.get("ISSUE361_FIXED_COHORT_ROOT", Path(__file__).resolve().parents[2])
)


class NoServiceReads:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unexpected service read: {name}")


@pytest.fixture
def relocated_cohort(tmp_path: Path) -> Path:
    root = tmp_path / "frozen-evidence"
    shutil.copytree(SOURCE_ROOT / COHORT_PATH, root / COHORT_PATH)
    shutil.copy2(SOURCE_ROOT / PROTOCOL_PATH, root / PROTOCOL_PATH)
    return root


@pytest.fixture
def fixed_plan() -> HistoryReplayPlanV1:
    manifest = json.loads(
        (SOURCE_ROOT / COHORT_PATH / "capture_manifest.json").read_bytes()
    )
    origins = []
    for row in manifest["issuers"]:
        snapshot = json.loads(
            gzip.decompress((SOURCE_ROOT / row["snapshot_path"]).read_bytes())
        )
        filings = _filings(snapshot, row["issuer_id"])
        decision = next(f for f in filings if f.accession == row["decision_accession"])
        origins.append(ReplayOriginV1(decision=decision, filings=filings))
    return HistoryReplayPlanV1(
        cohort_digest=FIXED_COHORT_DIGEST,
        mapping_version="unapproved-no-releases",
        runtime={"evidence_class": "engineering_boundary_check"},
        models=tuple(
            ReplayModelPinV1(
                model_id=p.model_id,
                model_version=p.model_version,
                policy_id=p.policy_id,
                policy_version=p.policy_version,
                policy_digest=p.policy_digest,
            )
            for p in initial_policy_records()
            if p.model_id in {"fcff_dcf", "transition_fcff_dcf"}
        ),
        origins=tuple(origins),
    )


def test_relocated_fixed_inputs_preserve_artifact_bytes_and_all_abstentions(
    fixed_plan: HistoryReplayPlanV1, relocated_cohort: Path
) -> None:
    service = cast(HistoryReplayService, NoServiceReads())
    original = run_history_replay(service, fixed_plan, cohort_root=SOURCE_ROOT)
    relocated = run_history_replay(service, fixed_plan, cohort_root=relocated_cohort)
    assert canonical_bytes(original) == canonical_bytes(relocated)
    assert len(relocated["forecast"]["rows"]) == 200
    assert relocated["report"]["composer_invocations"] == 0
    assert all(row["status"] == "abstain" for row in relocated["forecast"]["rows"])
    assert relocated["report"]["supported_history_threshold"] is None


def test_substitute_cohort_rejected_before_reading_a_missing_input_root(
    fixed_plan: HistoryReplayPlanV1, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="fixed SEC cohort digest"):
        run_history_replay(
            cast(HistoryReplayService, NoServiceReads()),
            fixed_plan.model_copy(update={"cohort_digest": "0" * 64}),
            cohort_root=tmp_path / "absent",
        )


@pytest.mark.parametrize(
    "relative_path,error",
    [
        (COHORT_PATH / "capture_manifest.json", "fixed SEC cohort digest"),
        (PROTOCOL_PATH, "protocol hash mismatch"),
        (COHORT_PATH / "frame_manifest.json", "frame_manifest hash mismatch"),
        (COHORT_PATH / "snapshots/0001539778.json.gz", "snapshot hash mismatch"),
    ],
)
def test_mutated_frozen_input_fails_before_any_service_read(
    fixed_plan: HistoryReplayPlanV1,
    relocated_cohort: Path,
    relative_path: Path,
    error: str,
) -> None:
    path = relocated_cohort / relative_path
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match=error):
        run_history_replay(
            cast(HistoryReplayService, NoServiceReads()),
            fixed_plan,
            cohort_root=relocated_cohort,
        )


def test_changed_decision_is_rejected_with_intact_relocated_evidence(
    fixed_plan: HistoryReplayPlanV1, relocated_cohort: Path
) -> None:
    origin = fixed_plan.origins[0]
    changed_date = datetime(2016, 1, 1, tzinfo=origin.decision.accepted_at.tzinfo)
    changed = replace(origin.decision, accepted_at=changed_date)
    mutated_origin = origin.model_copy(
        update={
            "decision": changed,
            "filings": tuple(
                changed if f == origin.decision else f for f in origin.filings
            ),
        }
    )
    with pytest.raises(ValueError, match="fixed decision or filing inventory"):
        run_history_replay(
            cast(HistoryReplayService, NoServiceReads()),
            fixed_plan.model_copy(
                update={"origins": (mutated_origin, *fixed_plan.origins[1:])}
            ),
            cohort_root=relocated_cohort,
        )
