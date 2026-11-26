from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fundamental_service.contracts import QualityStatus
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.fiscal_statement_contracts import (
    AmendedFiscalRevisionV1,
    FiscalBasisFilingV1,
    FiscalBasisObservationV1,
    FiscalComparativePairV1,
    FiscalDurationPeriodV1,
    FiscalObservationV1,
    FiscalPeriodTargetV1,
    FiscalProjectionInputV1,
    FiscalReportingBasisV1,
    FiscalRevisionBasisProofV1,
    FiscalRevisionBridgeV1,
    FiscalSourceLocatorV1,
    FiscalTtmWindowV1,
    ReportedFiscalYearV1,
    ReportedInstantV1,
    ReportedQuarterV1,
    ReportedYtdV1,
    UnsupportedDurationV1,
)
from fundamental_service.fiscal_statement_policy import fiscal_statement_policy
from fundamental_service.fiscal_statement_projection import project_fiscal_statements
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.statement_contracts import StatementScopeV1
from pydantic import ValidationError

FIXTURES = Path(__file__).parent / "fixtures/quarterly-statements"
SOURCE_ROOT = Path(__file__).parents[1] / "src/fundamental_service"
SOURCE_REVISION = "0" * 40


def _json(path: Path):
    return json.loads(path.read_bytes())


def _timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _span(raw):
    return FiscalDurationPeriodV1(
        start=date.fromisoformat(raw["start_date"]),
        end=date.fromisoformat(raw["end_date"]),
        fiscal_year_start=date.fromisoformat(raw["fiscal_year_start"]),
        fiscal_year=int(raw["fiscal_year_focus"]),
        fiscal_period=raw["fiscal_period_focus"],
        inclusive_days=raw["inclusive_calendar_days"],
    )


def _observation_period(raw, target_spans):
    period = raw["period"]
    if period["period_type"] == "instant":
        return ReportedInstantV1(instant=date.fromisoformat(period["instant"]))
    start = date.fromisoformat(period["start_date"])
    end = date.fromisoformat(period["end_date"])
    for target in target_spans:
        if target.start == start and target.end == end:
            return ReportedQuarterV1(
                period=target,
                applicability="quarter_and_ytd"
                if start == target.fiscal_year_start
                else "quarter",
            )
    for target in target_spans:
        if target.fiscal_year_start == start and target.end == end:
            span = target.model_copy(
                update={"start": start, "inclusive_days": (end - start).days + 1}
            )
            return (
                ReportedFiscalYearV1(period=span)
                if target.fiscal_period == "FY"
                else ReportedYtdV1(period=span)
            )
    for target in target_spans:
        if target.fiscal_year_start == start and 80 <= (end - start).days + 1 <= 105:
            return ReportedQuarterV1(
                period=target.model_copy(
                    update={
                        "start": start,
                        "end": end,
                        "inclusive_days": (end - start).days + 1,
                        "fiscal_period": "Q1",
                    }
                ),
                applicability="quarter_and_ytd",
            )
    return UnsupportedDurationV1(
        start=start, end=end, reason="outside_requested_fiscal_years"
    )


def _case_input(case_id):
    case = _json(FIXTURES / "cases" / f"{case_id}.json")
    reviewed = _json(FIXTURES / "basis" / f"cohort-{case_id}.json")
    registry = _json(FIXTURES / "basis/cohort-filings.json")
    cutoff = _timestamp(case["cutoff_at"])
    spans = tuple(_span(item["period"]) for item in reviewed["quarters"].values())
    targets = tuple(
        FiscalPeriodTargetV1(
            period_id=item["period"]["quarter_id"],
            period=_span(item["period"]),
            cutoff_at=cutoff,
            source_binding_digest=sha256_digest(item["period"]),
        )
        for item in reviewed["quarters"].values()
    )
    source_files = {
        item["accession_number"]: FIXTURES
        / "golden/sources"
        / (item["accession_number"] + ".json")
        for item in case["filings"]
    }
    raw_observations = {}
    observations = []
    for accession, path in source_files.items():
        source = _json(path)
        raw_observations.update(source["observations"])
        cash_concepts = {
            fact["qname"]
            for fact in source["observations"].values()
            if fact["row_id"]
            in {"cash_flow_beginning_balance", "cash_flow_ending_balance"}
        }
        assert len(cash_concepts) == 1
        cash_concept = next(iter(cash_concepts))
        cash_basis = (
            "cash_equivalents_and_restricted_cash"
            if "RestrictedCash" in cash_concept
            else "cash_and_equivalents"
        )
        for raw in source["observations"].values():
            basis = FiscalReportingBasisV1(
                issuer_id=raw["issuer_id"],
                security_id="AAPL" if raw["issuer_id"] == "0000320193" else "MSFT",
                security_scope="issuer",
                entity_scope=raw["entity_identifier"],
                currency="USD",
                unit=raw["unit_measures"][0],
                consolidation_scope=raw["consolidation_scope"],
                dimensions=tuple(
                    (item["dimension"], item["member"]) for item in raw["dimensions"]
                ),
                cash_basis=cash_basis if raw["statement"] == "cash_flow" else None,
                revision_basis_id=raw["revision_basis_id"],
            )
            observations.append(
                FiscalObservationV1(
                    observation_id=raw["observation_id"],
                    row_id=raw["row_id"],
                    statement=raw["statement"],
                    source_artifact_id="synthetic-fixture:" + _digest(path),
                    accession_number=accession,
                    form=raw["form"],
                    issuer_id=raw["issuer_id"],
                    accepted_at=_timestamp(raw["accepted_at"]),
                    available_at=_timestamp(raw["accepted_at"]),
                    filing_date=date.fromisoformat(raw["filing_date"]),
                    report_date=date.fromisoformat(raw["report_date"]),
                    period=_observation_period(raw, spans),
                    basis=basis,
                    source_locator=FiscalSourceLocatorV1(
                        primary_document_sha256=raw["primary_html_sha256"],
                        context_id=raw["context_id"],
                        fact_index=raw["fact_index"],
                        table_index=raw["table_index"],
                        row_index=raw["row_index"],
                    ),
                    concept=raw["qname"],
                    namespace_uri=raw["namespace_uri"],
                    source_fact_key=raw["observation_id"],
                    raw_text=raw["raw_text"],
                    value=Decimal(raw["canonical_decimal"]),
                    scale=int(raw["scale"]) if raw["scale"] is not None else None,
                    sign=raw["sign"],
                    decimals="INF"
                    if raw["decimals"] == "INF"
                    else int(raw["decimals"])
                    if raw["decimals"] is not None
                    else None,
                    quality=QualityStatus.PROVISIONAL
                    if accession == "0000950170-24-118967"
                    else QualityStatus.VERIFIED,
                    source_binding_digest=_digest(path),
                    parser_action_digest=sha256_digest(
                        ("synthetic-fixture-parser", accession)
                    ),
                    mapping_digest=sha256_digest(
                        ("synthetic-fixture-mapping", raw["row_id"], raw["qname"])
                    ),
                )
            )
    by_observation = {item.observation_id: item for item in observations}

    def proof(row_id, span, row_proof, review_path, component_periods=()):
        identities = set(row_proof["selected_observation_ids"])
        identities.update(row_proof.get("difference_observation_ids", []))
        pairs = row_proof.get("original_comparative_pairs", []) + row_proof.get(
            "same_filing_duplicate_pairs", []
        )
        for pair in pairs:
            identities.update(pair)
        if not identities:
            return None
        filings = []
        accessions = sorted(
            {by_observation[identity].accession_number for identity in identities}
        )
        for accession in accessions:
            filing = registry["filings"][accession]
            disclosures = tuple(
                ArtifactRefV1(
                    role="synthetic-fixture-disclosure",
                    artifact_id="disclosure:" + paragraph["sha256"],
                    content_hash=paragraph["sha256"],
                    media_type="text/plain",
                )
                for paragraphs in filing["disclosures"].values()
                for paragraph in paragraphs
            )
            assert disclosures
            filings.append(
                FiscalBasisFilingV1(
                    accession_number=accession,
                    primary_document_sha256=filing["primary_html_sha256"],
                    accepted_at=_timestamp(filing["accepted_at"]),
                    disclosure_refs=disclosures,
                )
            )
        return FiscalRevisionBasisProofV1(
            row_id=row_id,
            period=span,
            observations=tuple(
                FiscalBasisObservationV1(
                    observation_id=identity,
                    observation_digest=by_observation[identity].observation_digest,
                )
                for identity in sorted(identities)
            ),
            filings=tuple(filings),
            comparative_pairs=tuple(
                FiscalComparativePairV1(original_id=a, comparative_id=b)
                for a, b in pairs
            ),
            component_period_digests=tuple(
                sha256_digest(item) for item in component_periods
            ),
            source_revision=SOURCE_REVISION,
            cutoff_at=cutoff,
            public_available_at=max(filing.accepted_at for filing in filings),
            review_evidence_ref=ArtifactRefV1(
                role="synthetic-fixture-independent-basis",
                artifact_id="basis:" + _digest(review_path),
                content_hash=_digest(review_path),
                media_type="application/json",
            ),
        )

    proofs = []
    review_path = FIXTURES / "basis" / f"cohort-{case_id}.json"
    for quarter in reviewed["quarters"].values():
        for row_id, row_proof in quarter["rows"].items():
            item = proof(row_id, _span(quarter["period"]), row_proof, review_path)
            if item is not None:
                proofs.append(item)
    by_target = {item.period_id: item for item in targets}
    windows = []
    for window in reviewed["ttm"].values():
        quarters = tuple(by_target[identity] for identity in window["quarter_ids"])
        windows.append(
            FiscalTtmWindowV1(
                window_id=window["window_id"],
                quarters=quarters,
                source_binding_digest=sha256_digest(window["quarter_ids"]),
            )
        )
        first, last = quarters[0].period, quarters[-1].period
        span = first.model_copy(
            update={
                "end": last.end,
                "fiscal_year": last.fiscal_year,
                "fiscal_period": "TTM",
                "inclusive_days": window["inclusive_calendar_days"],
            }
        )
        for row_id, row_proof in window["rows"].items():
            item = proof(row_id, span, row_proof, review_path, quarters)
            if item is not None:
                proofs.append(item)
    source_files_digest = sha256_digest(
        {accession: _digest(path) for accession, path in source_files.items()}
    )
    return FiscalProjectionInputV1(
        observations=tuple(observations),
        scope=StatementScopeV1(
            issuer_id=case["issuer_id"],
            security_id="AAPL" if case["issuer_id"] == "0000320193" else "MSFT",
            security_scope="issuer",
            entity_scope=case["issuer_id"],
            currency="USD",
            unit="iso4217:USD",
        ),
        quarter_targets=targets,
        ttm_windows=tuple(windows),
        cutoff_at=cutoff,
        source_binding_digest=source_files_digest,
        basis_proofs=tuple(proofs),
        source_revision=SOURCE_REVISION,
        executable_digest=sha256_digest(
            {
                name: _digest(SOURCE_ROOT / name)
                for name in (
                    "fiscal_statement_contracts.py",
                    "fiscal_statement_policy.py",
                    "fiscal_statement_projection.py",
                )
            }
        ),
    )


def test_policy_matches_frozen_25_row_aggregation_contract():
    frozen = _json(FIXTURES / "issue495-row-policy.json")
    actual = fiscal_statement_policy()
    translate = {
        "additive_flow": "additive_flow",
        "instant": "period_end_instant",
        "cash_opening": "cash_flow_boundary",
        "cash_closing": "cash_flow_boundary",
    }
    assert sorted(
        (row.row_id, row.statement, translate[row.aggregation]) for row in actual.rows
    ) == sorted(
        (row["row_id"], row["statement"], row["aggregation"]) for row in frozen["rows"]
    )
    assert {item.family for item in actual.unsupported} == set(
        frozen["unsupported_row_families"]
    )


@pytest.mark.parametrize(
    "case_id", ["msft-historical", "aapl-historical", "msft-current", "aapl-current"]
)
def test_all_frozen_quarter_and_ttm_cells(case_id):
    request = _case_input(case_id)
    actual = project_fiscal_statements(request)
    quarter_by_key = {
        (target.period.end, node.row_id): node
        for index, target in enumerate(request.quarter_targets)
        for node in actual.quarter_nodes[index * 25 : (index + 1) * 25]
    }
    ttm_by_key = {
        (window.quarters[-1].period.end, node.row_id): node
        for index, window in enumerate(request.ttm_windows)
        for node in actual.ttm_nodes[index * 25 : (index + 1) * 25]
    }
    checked = 0
    for frequency, lookup in (("quarter", quarter_by_key), ("ttm", ttm_by_key)):
        for shard in sorted((FIXTURES / "golden" / frequency / case_id).glob("*.json")):
            expected = _json(shard)
            for cell in expected.get("cells", []):
                node = lookup[(date.fromisoformat(cell["end_date"]), cell["row_id"])]
                value = Decimal(cell["value"]) if cell["value"] is not None else None
                assert node.value == value, (
                    case_id,
                    frequency,
                    shard.name,
                    cell["row_id"],
                    node.reason_code,
                    node.source_observation_ids,
                )
                availability = {
                    "missing": "unavailable",
                    "reported_with_derived_crosscheck": "reported",
                    "reported_instant": "reported",
                    "as_of_instant": "reported",
                    "boundary_instant": "reported",
                }.get(cell["availability"], cell["availability"])
                assert node.availability == availability, (
                    case_id,
                    frequency,
                    shard.name,
                    cell["row_id"],
                    node.reason_code,
                )
                if cell["availability"] == "reported_with_derived_crosscheck":
                    assert node.verification_observation_ids
                if node.value is not None:
                    assert (
                        node.available_at is not None
                        and node.available_at <= request.cutoff_at
                    )
                    assert node.revision_basis_proof is not None
                checked += 1
    assert checked == 325
    assert canonical_bytes(project_fiscal_statements(request)) == canonical_bytes(
        actual
    )
    assert actual.quarter_periods == request.quarter_targets
    assert actual.ttm_windows == request.ttm_windows
    assert actual.supported_history_threshold is None
    assert actual.valuation_eligibility == "not_evaluated"
    by_id = {item.observation_id: item for item in request.observations}
    by_id.update({node.node_id: node for node in actual.nodes})
    for node in actual.nodes:
        if node.value is None:
            continue
        assert node.available_at >= node.revision_basis_proof.public_available_at
        for identity in (
            node.source_observation_ids
            + node.verification_observation_ids
            + node.verification_node_ids
        ):
            dependency = by_id[identity]
            if dependency.available_at is not None:
                assert node.available_at >= dependency.available_at
        for edge in node.input_edges:
            assert edge.input_id in by_id
            assert edge.coefficient in {-1, 1}
            assert node.available_at >= by_id[edge.input_id].available_at
        if node.verification_edges:
            assert [
                (edge.input_id, edge.coefficient) for edge in node.verification_edges
            ] == [
                (node.verification_observation_ids[0], 1),
                (node.verification_observation_ids[1], -1),
            ]
        if node.availability == "derived":
            assert (
                sum(
                    (
                        by_id[edge.input_id].value * edge.coefficient
                        for edge in node.input_edges
                    ),
                    Decimal(0),
                )
                == node.value
            )
    if case_id.startswith("aapl"):
        assert actual.quality is QualityStatus.PROVISIONAL
        assert all(
            check.status == "unresolved_missing_inputs"
            for check in actual.reconciliations
            if check.rule == "flows_plus_fx_equals_change"
        )
        assert any(
            window.quarters[0].period.start.year != window.quarters[-1].period.end.year
            for window in actual.ttm_windows
        )
        days = {
            (window.quarters[-1].period.end - window.quarters[0].period.start).days + 1
            for window in actual.ttm_windows
        }
        assert days <= {364, 371}


def _synthetic_input():
    raw = _json(FIXTURES / "issue495-boundary-cases.json")
    cutoff, accepted = _timestamp(raw["cutoff_at"]), _timestamp(raw["accepted_at"])
    year_start = date.fromisoformat(raw["fiscal_year_start"])
    targets = tuple(
        FiscalPeriodTargetV1(
            period_id=quarter["quarter_id"],
            period=FiscalDurationPeriodV1(
                start=date.fromisoformat(quarter["start_date"]),
                end=date.fromisoformat(quarter["end_date"]),
                fiscal_year_start=year_start,
                fiscal_year=2024,
                fiscal_period=quarter["fiscal_period_focus"],
                inclusive_days=(
                    date.fromisoformat(quarter["end_date"])
                    - date.fromisoformat(quarter["start_date"])
                ).days
                + 1,
            ),
            cutoff_at=cutoff,
            source_binding_digest="1" * 64,
        )
        for quarter in raw["quarters"]
    )
    scope = StatementScopeV1(
        issuer_id=raw["issuer_id"],
        security_id="SYNTHETIC",
        security_scope="issuer",
        entity_scope=raw["issuer_id"],
        currency="USD",
        unit="iso4217:USD",
    )
    basis = FiscalReportingBasisV1(
        **scope.model_dump(), revision_basis_id="synthetic-original"
    )
    observations = []

    def add(identity, row, statement, period, value):
        observations.append(
            FiscalObservationV1(
                observation_id=identity,
                row_id=row,
                statement=statement,
                source_artifact_id="synthetic-fixture",
                accession_number="synthetic-fixture-original",
                form="10-K",
                issuer_id=scope.issuer_id,
                accepted_at=accepted,
                available_at=accepted,
                filing_date=accepted.date(),
                report_date=date(2024, 6, 30),
                period=period,
                basis=basis.model_copy(
                    update={
                        "cash_basis": "cash_and_equivalents"
                        if statement == "cash_flow"
                        else None
                    }
                ),
                source_locator=FiscalSourceLocatorV1(
                    primary_document_sha256="2" * 64,
                    context_id=identity,
                    fact_index=len(observations),
                ),
                concept="synthetic:" + row,
                namespace_uri="https://example.com/synthetic/2024",
                source_fact_key=identity,
                raw_text=str(value),
                value=Decimal(value),
                decimals="INF",
                source_binding_digest="3" * 64,
                parser_action_digest="4" * 64,
                mapping_digest="5" * 64,
            )
        )

    for index, (target, value) in enumerate(zip(targets, ("100", "210", "330", "490"))):
        span = target.period.model_copy(
            update={
                "start": year_start,
                "inclusive_days": (target.period.end - year_start).days + 1,
            }
        )
        role = (
            ReportedQuarterV1(period=span, applicability="quarter_and_ytd")
            if index == 0
            else ReportedFiscalYearV1(period=span)
            if index == 3
            else ReportedYtdV1(period=span)
        )
        add(
            ("q1", "q2_ytd", "q3_ytd", "fy")[index],
            "revenue",
            "income_statement",
            role,
            value,
        )
        for row, amount in (
            ("operating_cash_flow", 10),
            ("investing_cash_flow", -3),
            ("financing_cash_flow", -2),
            ("effect_of_exchange_rates_on_cash", 0),
            ("net_change_in_cash", 5),
        ):
            add(
                target.period_id + "/" + row,
                row,
                "cash_flow",
                role,
                str(amount * (index + 1)),
            )
        add(
            target.period_id + "/total_assets",
            "total_assets",
            "balance_sheet",
            ReportedInstantV1(instant=target.period.end),
            str(880 + index * 10),
        )
        add(
            target.period_id + "/cash_flow_ending_balance",
            "cash_flow_ending_balance",
            "cash_flow",
            ReportedInstantV1(instant=target.period.end),
            str(30 + index * 5),
        )
    add(
        "q1/cash_flow_beginning_balance",
        "cash_flow_beginning_balance",
        "cash_flow",
        ReportedInstantV1(instant=date(2023, 6, 30)),
        "25",
    )
    return FiscalProjectionInputV1(
        observations=tuple(observations),
        scope=scope,
        quarter_targets=targets,
        ttm_windows=(
            FiscalTtmWindowV1(
                window_id="synthetic-ttm",
                quarters=targets,
                source_binding_digest="6" * 64,
            ),
        ),
        cutoff_at=cutoff,
        source_binding_digest="7" * 64,
        source_revision=SOURCE_REVISION,
        executable_digest="8" * 64,
    )


def _synthetic_proofs(request):
    proofs = []
    periods = [(target.period, ()) for target in request.quarter_targets]
    for window in request.ttm_windows:
        first, last = window.quarters[0].period, window.quarters[-1].period
        if first.start > last.end:
            continue
        periods.append(
            (
                first.model_copy(
                    update={
                        "end": last.end,
                        "inclusive_days": (last.end - first.start).days + 1,
                        "fiscal_period": "TTM",
                        "fiscal_year": last.fiscal_year,
                    }
                ),
                window.quarters,
            )
        )
    for row in fiscal_statement_policy().rows:
        observations = tuple(
            item
            for item in request.observations
            if (
                item.row_id == row.row_id
                or row.aggregation in {"cash_opening", "cash_closing"}
                and item.row_id
                in {"cash_flow_beginning_balance", "cash_flow_ending_balance"}
            )
            and item.available_at <= request.cutoff_at
            and not isinstance(item.filing_revision, AmendedFiscalRevisionV1)
        )
        if not observations:
            continue
        filings = {
            item.accession_number: FiscalBasisFilingV1(
                accession_number=item.accession_number,
                primary_document_sha256=item.source_locator.primary_document_sha256,
                accepted_at=item.accepted_at,
                disclosure_refs=(
                    ArtifactRefV1(
                        role="synthetic-fixture-disclosure",
                        artifact_id="synthetic-disclosure",
                        content_hash="9" * 64,
                        media_type="text/plain",
                    ),
                ),
            )
            for item in observations
        }
        for period, components in periods:
            proofs.append(
                FiscalRevisionBasisProofV1(
                    row_id=row.row_id,
                    period=period,
                    observations=tuple(
                        FiscalBasisObservationV1(
                            observation_id=item.observation_id,
                            observation_digest=item.observation_digest,
                        )
                        for item in observations
                    ),
                    filings=tuple(filings.values()),
                    component_period_digests=tuple(
                        sha256_digest(item) for item in components
                    ),
                    source_revision=request.source_revision,
                    cutoff_at=request.cutoff_at,
                    public_available_at=max(item.available_at for item in observations),
                    review_evidence_ref=ArtifactRefV1(
                        role="synthetic-fixture-review",
                        artifact_id="synthetic-review",
                        content_hash="a" * 64,
                        media_type="application/json",
                    ),
                )
            )
    return request.model_copy(update={"basis_proofs": tuple(proofs)})


def _mutated_synthetic(spec):
    request = _synthetic_input()
    observations = list(request.observations)
    targets = list(request.quarter_targets)
    quarters = list(request.ttm_windows[0].quarters)
    mutation = spec.get("mutation", {})
    if "remove_fact" in mutation:
        observations = [
            item
            for item in observations
            if item.observation_id != mutation["remove_fact"]
        ]
    if "add_fact" in mutation or mutation.get("add_conflicting_direct"):
        additions = (
            [mutation["add_fact"]]
            if "add_fact" in mutation
            else [
                dict(
                    observation_id="direct",
                    start_date="2023-10-01",
                    end_date="2023-12-31",
                    value="110",
                ),
                dict(
                    observation_id="other_direct",
                    start_date="2023-10-01",
                    end_date="2023-12-31",
                    value="111",
                ),
            ]
        )
        for added in additions:
            target = next(
                item for item in targets if str(item.period.end) == added["end_date"]
            )
            template = next(
                item
                for item in observations
                if item.row_id == "revenue"
                and item.period.period.end == target.period.end
            )
            role = (
                ReportedQuarterV1(period=target.period)
                if "start_date" in added
                else template.period
            )
            accepted = (
                _timestamp(added["accepted_at"])
                if "accepted_at" in added
                else template.accepted_at
            )
            update = dict(
                observation_id=added["observation_id"],
                value=Decimal(added["value"]),
                raw_text=added["value"],
                period=role,
                accepted_at=accepted,
                available_at=accepted,
                decimals=int(added["decimals"]) if "decimals" in added else "INF",
            )
            if "accepted_at" in added:
                update["accession_number"] = "synthetic-future"
            if added.get("form") == "10-Q/A":
                update.update(
                    form="10-Q/A",
                    filing_revision=AmendedFiscalRevisionV1(scope="unknown"),
                )
            observations.append(template.model_copy(update=update))
            if added.get("withhold_ytd"):
                observations = [
                    item
                    for item in observations
                    if item.observation_id not in {"q1", "q2_ytd"}
                ]
    if "fact" in mutation or "observation" in mutation:
        identity, field, value = (
            mutation.get("fact", mutation.get("observation")),
            mutation["field"],
            mutation["value"],
        )
        for index, item in enumerate(observations):
            if item.observation_id != identity:
                continue
            if field == "value":
                observations[index] = item.model_copy(
                    update={"value": Decimal(value), "raw_text": value}
                )
            else:
                field = "unit" if field == "unit_measures" else field
                value = (
                    value[0]
                    if field == "unit"
                    else (("sample:RegionAxis", "sample:US"),)
                    if field == "dimensions"
                    else value
                )
                observations[index] = item.model_copy(
                    update={"basis": item.basis.model_copy(update={field: value})}
                )
    if "remove_period" in mutation:
        targets = [
            item for item in targets if item.period_id != mutation["remove_period"]
        ]
    if "period" in mutation:
        index = next(
            index
            for index, item in enumerate(quarters)
            if item.period_id == mutation["period"]
        )
        target = quarters[index]
        if mutation["field"] == "quarter_id":
            quarters[index] = target.model_copy(update={"period_id": mutation["value"]})
        else:
            field = "start" if mutation["field"] == "start_date" else "end"
            raw = target.period.model_dump()
            raw[field] = date.fromisoformat(mutation["value"])
            raw["inclusive_days"] = (raw["end"] - raw["start"]).days + 1
            changed = target.model_copy(
                update={"period": FiscalDurationPeriodV1.model_validate(raw)}
            )
            quarters[index] = changed
            targets[index] = changed
    if "swap_periods" in mutation:
        left, right = mutation["swap_periods"]
        quarters[left], quarters[right] = quarters[right], quarters[left]
    if "remove_cell" in mutation:
        period_id, row = mutation["remove_cell"].split("/")
        target = next(item for item in targets if item.period_id == period_id)
        if row == "cash_flow_beginning_balance":
            observations = [
                item
                for item in observations
                if not (
                    isinstance(item.period, ReportedInstantV1)
                    and item.statement == "cash_flow"
                    and item.period.instant == target.period.start - timedelta(days=1)
                )
            ]
        elif row == "revenue":
            observations = [
                item
                for item in observations
                if item.observation_id
                != {"q1": "q1", "q2": "q2_ytd", "q3": "q3_ytd", "q4": "fy"}[period_id]
            ]
        else:
            observations = [
                item
                for item in observations
                if item.observation_id != mutation["remove_cell"]
            ]
    if spec["operation"] == "ttm_non_additive":
        template = observations[0]
        observations.extend(
            template.model_copy(
                update={
                    "observation_id": "unsupported-" + str(index),
                    "row_id": spec["row"]["row_id"],
                    "concept": spec["qname"],
                    "value": Decimal(value),
                }
            )
            for index, value in enumerate(spec["quarter_values"])
        )
    window = FiscalTtmWindowV1(
        window_id="synthetic-ttm",
        quarters=tuple(quarters),
        source_binding_digest="6" * 64,
    )
    return _synthetic_proofs(
        request.model_copy(
            update={
                "observations": tuple(observations),
                "quarter_targets": tuple(targets),
                "ttm_windows": (window,),
            }
        )
    )


BOUNDARIES = [
    item
    for item in _json(FIXTURES / "issue495-boundary-cases.json")["cases"]
    if item["operation"] not in {"source", "parse_filing"}
]


@pytest.mark.parametrize("spec", BOUNDARIES, ids=lambda spec: spec["id"])
def test_frozen_synthetic_domain_boundaries(spec):
    if spec["id"] in {"duplicate_quarter", "invalid_quarter_duration"}:
        with pytest.raises(ValidationError):
            _mutated_synthetic(spec)
        return
    request = _mutated_synthetic(spec)
    actual = project_fiscal_statements(request)
    if spec["operation"] == "ttm_non_additive":
        assert spec["row"]["row_id"] in actual.unsupported_rows
        assert not any(node.row_id == spec["row"]["row_id"] for node in actual.nodes)
        return
    row = spec.get("target", "revenue") if spec["operation"] == "ttm" else "revenue"
    if spec["operation"] == "quarter":
        end = next(
            item.period.end
            for item in request.quarter_targets
            if item.period_id == spec["target"]
        )
        node = next(
            node
            for node in actual.quarter_nodes
            if node.row_id == row and node.period.end == end
        )
    else:
        node = next(node for node in actual.ttm_nodes if node.row_id == row)
    expected = spec["expected"]
    availability = {
        "reported_with_derived_crosscheck": "reported",
        "reported_instant": "reported",
        "missing": "unavailable",
        "rejected": "unavailable",
    }.get(expected["availability"], expected["availability"])
    assert node.availability == availability, (node.reason_code, node.candidates)
    assert node.value == (
        Decimal(expected["value"]) if expected.get("value") is not None else None
    )
    if expected.get("outcome_code") not in {None, "selected"}:
        assert node.reason_code == expected["outcome_code"]
    if expected["availability"] == "reported_with_derived_crosscheck":
        assert node.verification_observation_ids
    if spec["id"] in {"post_cutoff_comparative", "amendment_unknown_scope"}:
        assert any(candidate.outcome == "rejected" for candidate in node.candidates)


def test_decimal_precision_dag_and_cash_reconciliations():
    request = _synthetic_input()
    base = project_fiscal_statements(_synthetic_proofs(request))
    assert all(
        check.status == "consistent_at_reported_precision"
        for check in base.reconciliations
    )
    assert all(
        check.status == "consistent_at_reported_precision"
        for check in base.cash_continuities
    )
    huge = Decimal("1234567890123456789012345678901234567890.1234567890123456789")
    observations = tuple(
        item.model_copy(
            update={
                "value": huge
                if item.observation_id == "q2_ytd"
                else Decimal("0.0000000000000000001"),
                "scale": 6,
            }
        )
        if item.observation_id in {"q1", "q2_ytd"}
        else item
        for item in request.observations
    )
    actual = project_fiscal_statements(
        _synthetic_proofs(request.model_copy(update={"observations": observations}))
    )
    q2 = next(
        node
        for node in actual.quarter_nodes
        if node.row_id == "revenue" and node.period.fiscal_period == "Q2"
    )
    assert (
        str(q2.value) == "1234567890123456789012345678901234567890.1234567890123456788"
    )
    assert [(edge.input_id, edge.coefficient) for edge in q2.input_edges] == [
        ("q2_ytd", 1),
        ("q1", -1),
    ]


@pytest.mark.parametrize(
    ("row_id", "direct_value", "exact_quarter", "availability"),
    (
        ("revenue", "110", "110.5", "reported"),
        ("revenue", "110", "109.5", "reported"),
        ("revenue", "110", "110.5000001", "conflict"),
        ("revenue", "110", "109.4999999", "conflict"),
        ("operating_income", "-110", "-109.5", "reported"),
        ("operating_income", "-110", "-110.5", "reported"),
        ("operating_income", "-110", "-109.4999999", "conflict"),
        ("operating_income", "-110", "-110.5000001", "conflict"),
    ),
)
def test_reported_quarter_accepts_precision_endpoints_but_rejects_beyond(
    row_id, direct_value, exact_quarter, availability
):
    request = _synthetic_input()
    current_ytd = Decimal(100) + Decimal(exact_quarter)
    observations = tuple(
        item.model_copy(
            update={
                "row_id": row_id,
                "value": current_ytd if item.observation_id == "q2_ytd" else item.value,
                "raw_text": str(current_ytd)
                if item.observation_id == "q2_ytd"
                else item.raw_text,
            }
        )
        if item.row_id == "revenue"
        else item
        for item in request.observations
    )
    template = next(item for item in observations if item.observation_id == "q2_ytd")
    direct = template.model_copy(
        update={
            "observation_id": "direct-precision-boundary",
            "period": ReportedQuarterV1(period=request.quarter_targets[1].period),
            "value": Decimal(direct_value),
            "raw_text": direct_value,
            "decimals": 0,
        }
    )
    actual = project_fiscal_statements(
        _synthetic_proofs(
            request.model_copy(update={"observations": observations + (direct,)})
        )
    )
    quarter = next(
        node
        for node in actual.quarter_nodes
        if node.row_id == row_id and node.period.fiscal_period == "Q2"
    )
    assert quarter.availability == availability
    assert quarter.value == (
        Decimal(direct_value) if availability == "reported" else None
    )
    assert quarter.reason_code == (
        None if availability == "reported" else "direct_derived_conflict"
    )
    if availability == "reported":
        assert tuple(
            (edge.input_id, edge.coefficient) for edge in quarter.verification_edges
        ) == (("q2_ytd", 1), ("q1", -1))


@pytest.mark.parametrize(
    ("current_ytd", "prior_ytd", "direct_value"),
    (("210", "110", "101"), ("-10", "100", "-111")),
)
def test_ytd_difference_retains_both_reported_precision_endpoints(
    current_ytd, prior_ytd, direct_value
):
    request = _synthetic_input()
    amounts = {"q1": prior_ytd, "q2_ytd": current_ytd}
    observations = tuple(
        item.model_copy(
            update={
                "row_id": "operating_income",
                **(
                    {
                        "value": Decimal(amounts[item.observation_id]),
                        "raw_text": amounts[item.observation_id],
                        "decimals": 0,
                    }
                    if item.observation_id in amounts
                    else {}
                ),
            }
        )
        if item.row_id == "revenue"
        else item
        for item in request.observations
    )
    template = next(item for item in observations if item.observation_id == "q2_ytd")
    direct = template.model_copy(
        update={
            "observation_id": "exact-direct-difference-boundary",
            "period": ReportedQuarterV1(period=request.quarter_targets[1].period),
            "value": Decimal(direct_value),
            "raw_text": direct_value,
            "decimals": "INF",
        }
    )
    actual = project_fiscal_statements(
        _synthetic_proofs(
            request.model_copy(update={"observations": observations + (direct,)})
        )
    )
    quarter = next(
        node
        for node in actual.quarter_nodes
        if node.row_id == "operating_income" and node.period.fiscal_period == "Q2"
    )
    assert (quarter.availability, quarter.value, quarter.reason_code) == (
        "reported",
        Decimal(direct_value),
        None,
    )


@pytest.mark.parametrize(
    ("values", "expected_value", "lower", "upper"),
    (
        (("10", "20", "30", "40"), "100", "98", "102"),
        (("-10", "-20", "-30", "-40"), "-100", "-102", "-98"),
    ),
)
def test_ttm_sum_retains_closed_precision_endpoints(
    values, expected_value, lower, upper
):
    request = _synthetic_input()
    originals = [item for item in request.observations if item.row_id == "revenue"]
    observations = tuple(
        item for item in request.observations if item.row_id != "revenue"
    ) + tuple(
        original.model_copy(
            update={
                "row_id": "operating_income",
                "period": ReportedQuarterV1(period=target.period),
                "value": Decimal(value),
                "raw_text": value,
                "decimals": 0,
            }
        )
        for original, target, value in zip(
            originals, request.quarter_targets, values, strict=True
        )
    )
    actual = project_fiscal_statements(
        _synthetic_proofs(request.model_copy(update={"observations": observations}))
    )
    ttm = next(node for node in actual.ttm_nodes if node.row_id == "operating_income")
    assert (ttm.availability, ttm.value) == ("derived", Decimal(expected_value))
    interval = ttm.precision_interval
    assert interval is not None
    assert (interval.lower, interval.upper) == (Decimal(lower), Decimal(upper))
    assert interval.lower_inclusive and interval.upper_inclusive


@pytest.mark.parametrize(
    ("opening", "opening_decimals", "closing", "closing_decimals", "status"),
    (
        ("25", 0, "30.5", "INF", "consistent_at_reported_precision"),
        ("25.5", "INF", "30", 0, "consistent_at_reported_precision"),
        ("25", 0, "30.5000001", "INF", "conflict"),
    ),
)
def test_cash_reconciliation_uses_signed_precision_endpoints(
    opening, opening_decimals, closing, closing_decimals, status
):
    request = _synthetic_input()
    changes = {
        "q1/cash_flow_beginning_balance": (opening, opening_decimals),
        "q1/cash_flow_ending_balance": (closing, closing_decimals),
    }
    observations = tuple(
        item.model_copy(
            update={
                "value": Decimal(changes[item.observation_id][0]),
                "raw_text": changes[item.observation_id][0],
                "decimals": changes[item.observation_id][1],
            }
        )
        if item.observation_id in changes
        else item
        for item in request.observations
    )
    actual = project_fiscal_statements(
        _synthetic_proofs(request.model_copy(update={"observations": observations}))
    )
    reconciliation = next(
        check
        for check in actual.reconciliations
        if check.period_id == "q1"
        and check.frequency == "quarter"
        and check.rule == "opening_plus_change_equals_closing"
    )
    assert reconciliation.status == status


def test_unknown_precision_and_cash_discontinuity_remain_explicit():
    request = _synthetic_input()
    observations = tuple(
        item.model_copy(update={"value": Decimal(99)})
        if item.observation_id == "q2/cash_flow_ending_balance"
        else item
        for item in request.observations
    )
    closing = next(
        item
        for item in observations
        if item.observation_id == "q2/cash_flow_ending_balance"
    )
    opening = closing.model_copy(
        update={
            "observation_id": "q3/opening",
            "row_id": "cash_flow_beginning_balance",
            "value": Decimal(35),
            "available_at": request.cutoff_at,
        }
    )
    observations += (opening,)
    actual = project_fiscal_statements(
        _synthetic_proofs(request.model_copy(update={"observations": observations}))
    )
    assert any(
        check.status == "conflict" and check.reason_code == "cash_continuity_conflict"
        for check in actual.cash_continuities
    )
    assert all(
        node.availability == "conflict"
        for node in actual.ttm_nodes
        if node.statement == "cash_flow"
    )
    no_precision = tuple(
        item.model_copy(update={"decimals": None}) for item in request.observations
    )
    unknown = project_fiscal_statements(
        _synthetic_proofs(request.model_copy(update={"observations": no_precision}))
    )
    assert all(
        check.status == "unresolved_precision" for check in unknown.reconciliations
    )


def test_later_unknown_amendment_cannot_reselect_original():
    request = _synthetic_input()
    original = next(
        item for item in request.observations if item.observation_id == "q2_ytd"
    )
    amendment = original.model_copy(
        update={
            "observation_id": "synthetic-unknown-amendment",
            "accession_number": "synthetic-amendment",
            "value": Decimal(999),
            "form": "10-Q/A",
            "filing_revision": AmendedFiscalRevisionV1(
                scope="unknown", amends_accession=original.accession_number
            ),
            "available_at": request.cutoff_at,
        }
    )
    actual = project_fiscal_statements(
        _synthetic_proofs(
            request.model_copy(
                update={"observations": request.observations + (amendment,)}
            )
        )
    )
    quarter = next(
        node
        for node in actual.quarter_nodes
        if node.row_id == "revenue" and node.period.fiscal_period == "Q2"
    )
    assert quarter.value is None
    assert quarter.reason_code == "revision_scope_unavailable"
    after = amendment.model_copy(
        update={"available_at": request.cutoff_at + timedelta(seconds=1)}
    )
    old_cutoff = project_fiscal_statements(
        _synthetic_proofs(
            request.model_copy(update={"observations": request.observations + (after,)})
        )
    )
    assert next(
        node.value
        for node in old_cutoff.quarter_nodes
        if node.row_id == "revenue" and node.period.fiscal_period == "Q2"
    ) == Decimal(110)


def test_fiscal_year_identity_is_checked_beyond_dates():
    request = _synthetic_input()
    observations = tuple(
        item.model_copy(
            update={
                "period": item.period.model_copy(
                    update={
                        "period": item.period.period.model_copy(
                            update={"fiscal_year": 2025}
                        )
                    }
                )
            }
        )
        if item.observation_id == "q2_ytd"
        else item
        for item in request.observations
    )
    actual = project_fiscal_statements(
        _synthetic_proofs(request.model_copy(update={"observations": observations}))
    )
    quarter = next(
        node
        for node in actual.quarter_nodes
        if node.row_id == "revenue" and node.period.fiscal_period == "Q2"
    )
    assert quarter.value is None
    assert quarter.reason_code == "current_ytd_unavailable"


def test_revision_bridge_requires_exact_observation_bindings():
    request = _synthetic_input()
    observations = tuple(
        item.model_copy(
            update={
                "basis": item.basis.model_copy(
                    update={"revision_basis_id": "synthetic-reviewed-revision"}
                )
            }
        )
        if item.observation_id == "q2_ytd"
        else item
        for item in request.observations
    )
    bound = _synthetic_proofs(request.model_copy(update={"observations": observations}))
    proofs = tuple(
        proof.model_copy(
            update={
                "revision_bridges": (
                    FiscalRevisionBridgeV1(
                        observations=proof.observations,
                        disclosure_refs=(proof.review_evidence_ref,),
                    ),
                )
            }
        )
        for proof in bound.basis_proofs
    )
    bridged = bound.model_copy(update={"basis_proofs": proofs})
    actual = project_fiscal_statements(bridged)
    assert next(
        node.value
        for node in actual.quarter_nodes
        if node.row_id == "revenue" and node.period.fiscal_period == "Q2"
    ) == Decimal(110)
    assert next(
        node.value for node in actual.ttm_nodes if node.row_id == "revenue"
    ) == Decimal(490)
    changed = tuple(
        item.model_copy(update={"raw_text": "changed lexical source"})
        if item.observation_id == "q2_ytd"
        else item
        for item in observations
    )
    stale = project_fiscal_statements(
        bridged.model_copy(update={"observations": changed})
    )
    assert (
        next(
            node.value
            for node in stale.quarter_nodes
            if node.row_id == "revenue" and node.period.fiscal_period == "Q2"
        )
        is None
    )


@pytest.mark.parametrize("invalid", [1.2, 10])
def test_decimal_boundary_rejects_float_and_integer_amounts(invalid):
    observation = _synthetic_input().observations[0]
    raw = observation.model_dump()
    raw["value"] = invalid
    with pytest.raises(ValidationError, match="require a Decimal"):
        FiscalObservationV1.model_validate(raw)
