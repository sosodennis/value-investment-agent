"""Prepare a source-bound historical proxy proposal; never publish a policy."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

from .history_mapping_audit import (
    ROOT,
    MappingAuditError,
    _array,
    _object,
    _text,
    _timestamp,
)
from .history_market_evidence import DEFAULT_OUTPUT
from .history_replay import (
    _ensure_tracked_tree_clean,
    _resolve_commit,
    _runtime_pins,
    _write_content_addressed,
)
from .history_replay_inputs import _digest
from .public_source import PUBLIC_SOURCE_SPECS
from .serialization import sha256_digest

REFERENCE_MANIFEST = DEFAULT_OUTPUT / "reference_sources/manifest.json"
PROPOSAL_VERSION = "historical-us-market-proxy-review-v1"


def _source(
    root: Path, record: dict[str, object], expected_id: str
) -> tuple[bytes, dict[str, object]]:
    if record.get("source_id") != expected_id:
        raise MappingAuditError("historical reference source identity mismatch")
    spec = next(spec for spec in PUBLIC_SOURCE_SPECS if spec.source_id == expected_id)
    uri = _text(record.get("uri"), "source URI")
    if not uri.startswith(spec.uri_prefix):
        raise MappingAuditError("historical reference URI is outside its register")
    path = (root / _text(record.get("path"), "source path")).resolve()
    if path.parent != root.resolve():
        raise MappingAuditError("historical reference path escapes its manifest")
    content = gzip.decompress(path.read_bytes())
    if _digest(content) != record.get("content_digest") or len(content) != record.get(
        "bytes"
    ):
        raise MappingAuditError("historical reference source digest mismatch")
    captured_at = _timestamp(record.get("captured_at"), "captured_at")
    if record.get("available_at") is not None:
        if _timestamp(record["available_at"], "available_at") > captured_at:
            raise MappingAuditError("source capture predates availability")
    return content, {**record, "terms_reference": spec.terms_reference}


def _workbook_roles(content: bytes) -> dict[str, dict[str, str]]:
    if version("xlrd") != "2.0.2":
        raise MappingAuditError("historical workbook parsing requires xlrd==2.0.2")
    import xlrd

    book = xlrd.open_workbook(file_contents=content)
    sheet = book.sheet_by_index(0)
    expected_headers = {
        0: "Industry Name",
        2: "Beta",
        4: "E/(D+E)",
        6: "Cost of Debt",
        9: "D/(D+E)",
    }
    if any(
        sheet.cell_value(18, column) != label
        for column, label in expected_headers.items()
    ):
        raise MappingAuditError("historical WACC workbook headers changed")
    if sheet.cell_value(9, 0) != "Risk Premium to Use for Equity =":
        raise MappingAuditError("historical ERP cell identity changed")
    updated = xlrd.xldate_as_datetime(sheet.cell_value(0, 1), book.datemode)
    if updated.date().isoformat() != "2015-01-05":
        raise MappingAuditError("historical workbook update date changed")
    rows = [
        row for row in range(sheet.nrows) if sheet.cell_value(row, 0) == "Total Market"
    ]
    if len(rows) != 1:
        raise MappingAuditError("historical total-market row is not unique")
    row = rows[0]
    cells = {
        "beta": (row, 2),
        "equity_risk_premium": (9, 3),
        "pre_tax_cost_of_debt": (row, 6),
        "debt_weight": (row, 9),
        "equity_weight": (row, 4),
    }
    result = {}
    for role, (cell_row, cell_column) in cells.items():
        value = Decimal(str(sheet.cell_value(cell_row, cell_column)))
        if not value.is_finite() or value < 0:
            raise MappingAuditError("historical market proxy value is invalid")
        result[role] = {
            "value": str(value),
            "unit": "dimensionless" if role == "beta" else "decimal_rate_or_weight",
            "sheet": sheet.name,
            "cell": xlrd.cellname(cell_row, cell_column),
            "source_row": "ERP input"
            if role == "equity_risk_premium"
            else "Total Market",
            "transformation": "Decimal(str(xlrd numeric cell)); no rounding or formula replacement",
            "as_of": "2015-01-05T00:00:00Z",
            "available_at": "2015-02-01T00:00:00Z",
        }
    if (
        Decimal(result["debt_weight"]["value"])
        + Decimal(result["equity_weight"]["value"])
        != 1
    ):
        raise MappingAuditError("historical capital weights do not sum to one")
    return result


def build_policy_proposal(
    *, market_evidence_path: Path, reference_manifest_path: Path = REFERENCE_MANIFEST
) -> dict[str, object]:
    """Expose all seven candidates, proxy meaning and missing approval for review."""
    evidence = _object(
        json.loads(gzip.decompress(market_evidence_path.read_bytes())),
        "market evidence",
    )
    evidence_digest = sha256_digest(evidence)
    if market_evidence_path.name != f"{evidence_digest}.json.gz":
        raise MappingAuditError("market evidence digest mismatch")
    references = _object(json.loads(reference_manifest_path.read_bytes()), "references")
    records = _object(references.get("sources"), "reference sources")
    source_bytes = {}
    source_refs = {}
    for role, source_id in (
        ("archive_index", "damodaran-archive-index"),
        ("wacc_2015", "damodaran-reference"),
        ("fomc_2012", "federal-reserve-policy"),
    ):
        content, record = _source(
            reference_manifest_path.parent, _object(records.get(role), role), source_id
        )
        source_bytes[role] = content
        source_refs[role] = record
    archive = source_bytes["archive_index"].decode("utf-8", errors="strict")
    if not re.search(
        r'href=["\'][^"\']*/archives/wacc14\.xls["\'][^>]*>\s*1/15', archive, re.I
    ):
        raise MappingAuditError(
            "archive index does not attest January 2015 publication"
        )
    fomc = re.sub(
        r"\s+", " ", re.sub(r"<[^>]+>", " ", source_bytes["fomc_2012"].decode("utf-8"))
    )
    citation = (
        "The Committee judges that inflation at the rate of 2 percent, as measured "
        "by the annual change in the price index for personal consumption expenditures"
    )
    if citation not in fomc or "January 25, 2012" not in fomc:
        raise MappingAuditError("FOMC historical date or inflation objective changed")
    shared_roles: dict[str, object] = {
        role: {
            **value,
            "source": source_refs["wacc_2015"],
            "proposed_method": "approved_policy",
            "meaning": "uniform historical US market proxy; not an issuer observation",
            "status": "approval_required",
        }
        for role, value in _workbook_roles(source_bytes["wacc_2015"]).items()
    }
    shared_roles["terminal_growth"] = {
        "value": "0.02",
        "unit": "decimal_rate_per_annum",
        "source": source_refs["fomc_2012"],
        "citation": citation,
        "as_of": "2012-01-25T00:00:00Z",
        "available_at": "2012-01-26T00:00:00Z",
        "proposed_method": "approved_policy",
        "meaning": "proposed no-real-growth proxy using the historical inflation objective; not an issuer growth fact",
        "status": "approval_required",
    }
    issuer_rows = []
    for value in _array(evidence.get("issuer_rows"), "issuer rows"):
        row = _object(value, "issuer")
        decision_at = _timestamp(row.get("decision_at"), "decision_at")
        roles = _object(row.get("roles"), "roles")
        rate = _object(roles.get("risk_free_rate"), "risk-free role")
        candidate = rate.get("candidate")
        available = all(
            _timestamp(_object(role, "proxy role")["available_at"], "available_at")
            <= decision_at
            for role in shared_roles.values()
        )
        if candidate is not None:
            available &= (
                _timestamp(
                    _object(candidate, "rate")["available_at"], "rate availability"
                )
                <= decision_at
            )
        issuer_rows.append(
            {
                "cik": row["cik"],
                "decision_accession": row["decision_accession"],
                "decision_at": row["decision_at"],
                "risk_free_rate": rate,
                "risk_free_source_key": row["source_key"],
                "shared_roles_digest": sha256_digest(shared_roles),
                "all_candidates_available_by_decision": available
                and candidate is not None,
                "policy_status": "proposed_unapproved",
            }
        )
    return {
        "schema_version": "historical-market-policy-proposal-v1",
        "proposal_version": PROPOSAL_VERSION,
        "runtime": {
            **_runtime_pins(_resolve_commit()),
            "xlrd_version": version("xlrd"),
        },
        "input_digest": sha256_digest(
            {"market_evidence": evidence_digest, "references": references}
        ),
        "market_evidence_digest": evidence_digest,
        "reference_manifest_digest": sha256_digest(references),
        "shared_roles": shared_roles,
        "source_refs": source_refs,
        "issuer_rows": issuer_rows,
        "selected_issuer_count": len(issuer_rows),
        "policy_status": "proposed_unapproved",
        "approval": None,
        "approved_policy_count": 0,
        "automatic_publication_permitted": False,
        "supported_history_threshold": None,
        "limitations": [
            "Historical source availability is supported by the publisher's archive and dated release; current archive capture is not itself a historical vintage.",
            "US total-market proxies are not issuer beta, issuer marginal borrowing cost or issuer market capital structure.",
            "Inflation objective is not an issuer growth forecast; terminal growth must also pass existing composer bounds.",
            "This proposal requires review; it cannot authorize a release or threshold promotion.",
        ],
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-evidence", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        _ensure_tracked_tree_clean(str(Path(__file__).resolve().relative_to(ROOT)))
        proposal = build_policy_proposal(market_evidence_path=args.market_evidence)
        artifact = _write_content_addressed(
            args.output_directory, "policy_proposal", proposal
        )
        print(
            json.dumps(
                {
                    "commit_sha": _resolve_commit(),
                    "command_result": "exit 0",
                    "input_digest": proposal["input_digest"],
                    "output_digest": artifact["sha256"],
                    "artifact": artifact,
                    "wrote": artifact["wrote"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError) as error:
        print(f"historical policy proposal failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
