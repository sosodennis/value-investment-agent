from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from lxml import etree, html
from pydantic import TypeAdapter

from fundamental_service.fiscal_statement_contracts import FiscalDurationPeriodV1
from fundamental_service.fiscal_statement_registry import (
    FiscalDisclosureScopeV1,
    FiscalFourthQuarterBoundaryV1,
    FiscalPrimaryFactScopeV1,
    FiscalPrimaryScopeV1,
    FiscalPrimaryTableV1,
    FiscalQuarterReviewV1,
    FiscalRegistryEntryV1,
    FiscalReportedQuarterContextV1,
    FiscalReviewedCoverageV1,
    FiscalRowBasisPlanV1,
    FiscalStatementRegistryV1,
    FiscalWindowBasisPlanV1,
)
from fundamental_service.ingestion import read_sec_xbrl_archive
from fundamental_service.serialization import canonical_bytes

type FiscalPeriodFocus = Literal["Q1", "Q2", "Q3", "FY"]


def load(path: Path):
    return json.loads(path.read_bytes())


def text(node) -> str:
    return " ".join(" ".join(node.itertext()).split())


def write(destination: Path, filename: str, model) -> FiscalRegistryEntryV1:
    raw = canonical_bytes(model) + b"\n"
    if len(raw) > 500_000:
        raise ValueError("fiscal scope exceeds its resource limit")
    destination.joinpath(filename).write_bytes(raw)
    return FiscalRegistryEntryV1(
        filename=filename, sha256=hashlib.sha256(raw).hexdigest()
    )


def period(raw) -> FiscalDurationPeriodV1:
    return FiscalDurationPeriodV1(
        start=date.fromisoformat(raw["start_date"]),
        end=date.fromisoformat(raw["end_date"]),
        fiscal_year_start=date.fromisoformat(raw["fiscal_year_start"]),
        fiscal_year=int(raw["fiscal_year_focus"]),
        fiscal_period=raw["fiscal_period_focus"],
        inclusive_days=raw["inclusive_calendar_days"],
    )


def rows(raw) -> tuple[FiscalRowBasisPlanV1, ...]:
    result = []
    for row_id, review in sorted(raw.items()):
        pairs = review.get("original_comparative_pairs", []) + review.get(
            "same_filing_duplicate_pairs", []
        )
        ids = set(review["selected_observation_ids"]) | set(
            review.get("difference_observation_ids", [])
        )
        ids.update(identity for pair in pairs for identity in pair)
        result.append(
            FiscalRowBasisPlanV1(
                row_id=row_id,
                observation_ids=tuple(sorted(ids)),
                comparative_pairs=tuple(tuple(pair) for pair in pairs),
            )
        )
    return tuple(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    filings = load(args.fixture_root / "basis/cohort-filings.json")["filings"]
    source_entries = []
    for path in sorted(args.fixture_root.joinpath("golden/sources").glob("*.json")):
        frozen = load(path)
        source, observations = frozen["source"], frozen["observations"]
        archive_receipt = next(
            item
            for item in source["response_receipts"]
            if "xbrl_archive" in item["response_role"]
        )
        digest = archive_receipt["content_hash"]
        archived = args.source_root / "content" / digest[:2] / (digest + ".bin")
        archive = archived.read_bytes()
        if hashlib.sha256(archive).hexdigest() != digest:
            raise ValueError("retained archive differs")
        member = read_sec_xbrl_archive(
            archive, primary_document=source["primary_document"], dts_filenames=()
        )[source["primary_document"]]
        root = etree.fromstring(
            member,
            etree.XMLParser(resolve_entities=False, no_network=True, recover=True),
        )
        facts = root.xpath(
            '//*[local-name()="nonFraction" or local-name()="nonNumeric" or local-name()="fraction"][@name]'
        )
        tables = root.xpath('//*[local-name()="table"]')
        table_positions = {item: index for index, item in enumerate(tables)}
        primary_tables = tuple(
            FiscalPrimaryTableV1(
                statement=statement,
                table_index=item["table_index"],
                table_sha256=hashlib.sha256(
                    etree.tostring(tables[item["table_index"]], method="c14n")
                ).hexdigest(),
                missing_rows=tuple(
                    row["row_id"]
                    for row in load(args.fixture_root / "issue495-row-policy.json")[
                        "rows"
                    ]
                    if row["statement"] == statement
                    and row["row_id"]
                    not in {
                        observation["row_id"] for observation in observations.values()
                    }
                ),
            )
            for statement, item in sorted(source["primary_statement_tables"].items())
        )
        cash_names = {
            item["qname"]
            for item in observations.values()
            if item["row_id"]
            in {"cash_flow_beginning_balance", "cash_flow_ending_balance"}
        }
        if len(cash_names) != 1:
            raise ValueError("cash basis is not uniquely disclosed")
        cash_basis = (
            "cash_equivalents_and_restricted_cash"
            if "RestrictedCash" in next(iter(cash_names))
            else "cash_and_equivalents"
        )
        scoped = []
        for observation in observations.values():
            element = facts[observation["fact_index"]]
            table = next(
                (
                    node
                    for node in element.iterancestors()
                    if etree.QName(node).localname == "table"
                ),
                None,
            )
            row = next(
                (
                    node
                    for node in element.iterancestors()
                    if etree.QName(node).localname == "tr"
                ),
                None,
            )
            if table is None or row is None:
                raise ValueError("reviewed fact is outside a statement table row")
            actual_row = list(table.xpath('.//*[local-name()="tr"]')).index(row)
            if (
                element.get("name"),
                element.get("contextRef"),
                table_positions[table],
                actual_row,
            ) != (
                observation["qname"],
                observation["context_id"],
                observation["table_index"],
                observation["row_index"],
            ):
                raise ValueError(
                    "archive primary fact position differs from reviewed scope"
                )
            p = observation["period"]
            scoped.append(
                FiscalPrimaryFactScopeV1(
                    observation_id=observation["observation_id"],
                    row_id=observation["row_id"],
                    statement=observation["statement"],
                    fact_index=observation["fact_index"],
                    fact_id=element.get("id", ""),
                    table_index=observation["table_index"],
                    row_index=observation["row_index"],
                    context_id=observation["context_id"],
                    concept=observation["qname"],
                    namespace_uri=observation["namespace_uri"],
                    period_start=date.fromisoformat(p["start_date"])
                    if p.get("start_date")
                    else None,
                    period_end=date.fromisoformat(p["end_date"])
                    if p.get("end_date")
                    else None,
                    instant=date.fromisoformat(p["instant"])
                    if p.get("instant")
                    else None,
                    unit=observation["unit_measures"][0],
                    cash_basis=cash_basis
                    if observation["statement"] == "cash_flow"
                    else None,
                )
            )
        html_root = html.fromstring(member)
        document = html_root.getroottree()
        paragraphs = {
            document.getpath(node): node for node in document.iter("p", "div")
        }
        disclosures = []
        for purpose, items in sorted(
            filings[source["accession_number"]]["disclosures"].items()
        ):
            for item in items:
                node = paragraphs.get(item["xpath"])
                if (
                    node is None
                    or hashlib.sha256(text(node).encode()).hexdigest() != item["sha256"]
                ):
                    raise ValueError(
                        "archive accounting disclosure differs from reviewed paragraph"
                    )
                disclosures.append(
                    FiscalDisclosureScopeV1(
                        purpose=purpose, xpath=item["xpath"], text_sha256=item["sha256"]
                    )
                )
        dei = {}
        for node in facts:
            if node.get("name") in {
                "dei:DocumentFiscalYearFocus",
                "dei:DocumentFiscalPeriodFocus",
            }:
                dei[node.get("name")] = text(node)
        source_scope = FiscalPrimaryScopeV1(
            issuer_id=source["issuer_id"],
            accession_number=source["accession_number"],
            form=source["form"],
            accepted_at=datetime.fromisoformat(
                source["accepted_at"].replace("Z", "+00:00")
            ),
            report_date=date.fromisoformat(source["reported_period_end"]),
            primary_document=source["primary_document"],
            primary_member_sha256=hashlib.sha256(member).hexdigest(),
            archive_sha256=digest,
            fiscal_year_focus=int(dei["dei:DocumentFiscalYearFocus"]),
            fiscal_period_focus=TypeAdapter(FiscalPeriodFocus).validate_python(
                dei["dei:DocumentFiscalPeriodFocus"]
            ),
            tables=primary_tables,
            facts=tuple(scoped),
            disclosures=tuple(disclosures),
            reviewed_source_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        source_entries.append(
            write(
                args.destination,
                "fiscal-scope-" + source["accession_number"] + ".json",
                source_scope,
            )
        )
    coverage_entries = []
    for path in sorted(args.fixture_root.joinpath("basis").glob("cohort-*-*.json")):
        review = load(path)
        quarters = tuple(
            FiscalQuarterReviewV1(
                accession_number=item["period"]["accession_number"],
                period=period(item["period"]),
                period_source=FiscalFourthQuarterBoundaryV1(
                    annual_context_id=item["period"]["period_source"][
                        "fiscal_year_context_id"
                    ],
                    preceding_accession_number=item["period"]["period_source"][
                        "preceding_quarter_accession"
                    ],
                    preceding_quarter_end=date.fromisoformat(
                        item["period"]["period_source"]["preceding_quarter_end"]
                    ),
                )
                if item["period"]["period_source"]["kind"]
                == "annual_duration_context_plus_preceding_quarter_boundary"
                else FiscalReportedQuarterContextV1(
                    fact_index=item["period"]["period_source"]["fact_index"],
                    context_id=item["period"]["period_source"]["context_id"],
                ),
                rows=rows(item["rows"]),
            )
            for item in review["quarters"].values()
        )
        by_id = {
            item["period"]["quarter_id"]: date.fromisoformat(item["period"]["end_date"])
            for item in review["quarters"].values()
        }
        windows = tuple(
            FiscalWindowBasisPlanV1(
                end=by_id[item["quarter_ids"][-1]],
                quarter_ends=tuple(by_id[identity] for identity in item["quarter_ids"]),
                rows=rows(item["rows"]),
            )
            for item in review["ttm"].values()
        )
        coverage_scope = FiscalReviewedCoverageV1(
            issuer_id=review["issuer_id"],
            source_accessions=tuple(review["source_accessions"]),
            quarters=quarters,
            ttm_windows=windows,
            reviewed_basis_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        coverage_entries.append(
            write(
                args.destination,
                "fiscal-coverage-"
                + review["issuer_id"]
                + "-"
                + str(quarters[-1].period.end)
                + ".json",
                coverage_scope,
            )
        )
    registry = FiscalStatementRegistryV1(
        sources=tuple(source_entries), coverage=tuple(coverage_entries)
    )
    raw = canonical_bytes(registry) + b"\n"
    (args.destination / "fiscal-statement-registry-v1.json").write_bytes(raw)
    print(
        json.dumps(
            {
                "sources": len(source_entries),
                "coverage_scopes": len(coverage_entries),
                "registry_digest": hashlib.sha256(raw).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
