import gzip
import json
from pathlib import Path

import pytest

from fundamental_service import history_policy_proposal as proposal
from fundamental_service.history_replay import _write_content_addressed
from fundamental_service.serialization import sha256_digest

MARKET_EVIDENCE = (
    proposal.DEFAULT_OUTPUT
    / "review/2c17fd3e0a6022e70ab07e92241ec010541480d6c99662bd3fb9394e80979580.json.gz"
)


def test_historical_proxy_proposal_has_seven_dated_roles_and_no_approval(
    tmp_path: Path,
) -> None:
    result = proposal.build_policy_proposal(market_evidence_path=MARKET_EVIDENCE)
    assert result["selected_issuer_count"] == 100
    assert result["approval"] is None
    assert result["approved_policy_count"] == 0
    assert result["automatic_publication_permitted"] is False
    assert result["supported_history_threshold"] is None
    shared = proposal._object(result["shared_roles"], "shared")
    rows = [
        proposal._object(row, "issuer")
        for row in proposal._array(result["issuer_rows"], "issuers")
    ]
    assert set(shared) == {
        "beta",
        "equity_risk_premium",
        "pre_tax_cost_of_debt",
        "debt_weight",
        "equity_weight",
        "terminal_growth",
    }
    assert proposal._object(shared["equity_risk_premium"], "ERP")["value"] == "0.0575"
    assert proposal._object(shared["terminal_growth"], "growth")["value"] == "0.02"
    assert all(row["all_candidates_available_by_decision"] for row in rows)
    assert all(row["policy_status"] == "proposed_unapproved" for row in rows)
    assert len({row["cik"] for row in rows}) == 100
    first = _write_content_addressed(tmp_path, "proposal", result)
    repeat = _write_content_addressed(
        tmp_path,
        "proposal",
        proposal.build_policy_proposal(market_evidence_path=MARKET_EVIDENCE),
    )
    assert first["sha256"] == repeat["sha256"]
    assert repeat["wrote"] is False


def test_reference_integrity_is_checked_before_workbook_parsing(tmp_path: Path) -> None:
    refs = json.loads(proposal.REFERENCE_MANIFEST.read_bytes())
    for row in refs["sources"].values():
        path = tmp_path / row["path"]
        path.write_bytes(
            (proposal.REFERENCE_MANIFEST.parent / row["path"]).read_bytes()
        )
    path = tmp_path / refs["sources"]["wacc_2015"]["path"]
    path.write_bytes(gzip.compress(b"changed workbook", mtime=0))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(refs))
    with pytest.raises(ValueError, match="source digest mismatch"):
        proposal.build_policy_proposal(
            market_evidence_path=MARKET_EVIDENCE, reference_manifest_path=manifest
        )


def test_changed_reference_bytes_require_a_new_review_digest(tmp_path: Path) -> None:
    first = proposal.build_policy_proposal(market_evidence_path=MARKET_EVIDENCE)
    refs = json.loads(proposal.REFERENCE_MANIFEST.read_bytes())
    for row in refs["sources"].values():
        path = tmp_path / row["path"]
        path.write_bytes(
            (proposal.REFERENCE_MANIFEST.parent / row["path"]).read_bytes()
        )
    refs["sources"]["wacc_2015"]["capture_method"] += "; additional review annotation"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(refs))
    second = proposal.build_policy_proposal(
        market_evidence_path=MARKET_EVIDENCE, reference_manifest_path=manifest
    )
    assert first["reference_manifest_digest"] != second["reference_manifest_digest"]
    assert first["input_digest"] != second["input_digest"]
    assert sha256_digest(first) != sha256_digest(second)
