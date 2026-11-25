from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from lxml import etree

from .fiscal_classification_contracts import FiscalSourceAccountingReviewV1
from .fiscal_classification_source import FiscalClassificationSource
from .fiscal_statement_mapping import transcribe_fiscal_amount
from .fiscal_validation_contracts import FiscalValidationCompleteRefusedV1
from .ingestion import read_sec_xbrl_archive
from .snapshots import SnapshotError


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_CLASSIFICATION_REVIEW_INVALID", message)


def _namespace(node: etree._Element, qname: str) -> str | None:
    return (
        node.nsmap.get(qname.split(":", 1)[0]) if ":" in qname else node.nsmap.get(None)
    )


def _one(root: etree._Element, local: str, identity: str) -> etree._Element:
    matches = root.xpath(
        "//*[local-name()=$local][@id=$identity]", local=local, identity=identity
    )
    if len(matches) != 1:
        raise _invalid("review requires a unique original context or unit")
    return matches[0]


def _uncertainty(decimals: str) -> Decimal:
    if decimals == "INF":
        return Decimal(0)
    try:
        precision = int(decimals)
        if abs(precision) > 1000:
            raise ValueError
        return Decimal(5).scaleb(-precision - 1)
    except (ValueError, InvalidOperation) as error:
        raise _invalid("review requires explicit bounded source precision") from error


def verify_fiscal_source_review(
    source: FiscalClassificationSource,
    review: FiscalSourceAccountingReviewV1,
    *,
    check_deadline: Callable[[], float],
) -> None:
    if review.scope != source.scope:
        raise _invalid("review does not bind the exact rebuilt source-use scope")
    outcome = source.evidence.outcome
    if not isinstance(outcome, FiscalValidationCompleteRefusedV1):
        raise _invalid("classification review requires raw-refused evidence")
    report = outcome.claim.report
    focus = source.witness.witness.actual_focus
    finding = source.witness.witness.raw_finding
    if (
        set(report.blocking_finding_codes()) != {"DQC.US.0015.5970"}
        or finding.code != "DQC.US.0015.5970"
        or finding.rule_severity != "error"
        or finding.severity != "warning"
        or finding not in report.findings
    ):
        raise _invalid("review cannot classify another or critical raw diagnostic")
    member = read_sec_xbrl_archive(
        source.archive,
        primary_document=source.evidence.request.filing.primary_document,
        dts_filenames=(),
    )[source.evidence.request.filing.primary_document]
    if hashlib.sha256(member).hexdigest() != outcome.integrity.archive_member_hash:
        raise _invalid("review original member differs from source integrity")
    try:
        root = etree.fromstring(
            member,
            etree.XMLParser(resolve_entities=False, no_network=True, recover=False),
        )
        tables = root.xpath('//*[local-name()="table"]')
        for item in review.facts:
            check_deadline()
            matches = root.xpath("//*[@id=$identity]", identity=item.fact_id)
            if len(matches) != 1:
                raise _invalid("review fact is not uniquely located in the original")
            node = matches[0]
            fact = item.fact
            table = next(
                (
                    p
                    for p in node.iterancestors()
                    if etree.QName(p).localname == "table"
                ),
                None,
            )
            row = next(
                (p for p in node.iterancestors() if etree.QName(p).localname == "tr"),
                None,
            )
            if table is None or row is None:
                raise _invalid("review fact has no original table and row")
            if (
                etree.QName(node).localname != "nonFraction"
                or node.get("name") != fact.concept
                or _namespace(node, fact.concept) != fact.namespace_uri
                or node.get("contextRef") != fact.context_id
                or tables.index(table) != item.table_index
                or table.xpath('.//*[local-name()="tr"]').index(row) != item.row_index
                or hashlib.sha256(etree.tostring(table, method="c14n")).hexdigest()
                != item.table_sha256
                or hashlib.sha256(etree.tostring(row, method="c14n")).hexdigest()
                != item.row_sha256
                or " ".join(" ".join(node.itertext()).split()) != item.raw_lexical
                or node.get("sign") != item.raw_sign
                or int(node.get("scale", "0")) != item.raw_scale
                or node.get("decimals") != item.raw_decimals
                or fact.decimals != item.raw_decimals
                or fact.scale != item.raw_scale
                or not fact.is_numeric
                or fact not in report.facts
                or transcribe_fiscal_amount(node) != item.value
                or Decimal(fact.value) != item.value
            ):
                raise _invalid(
                    "review changes the original fact, location, sign or precision"
                )
            context = _one(root, "context", fact.context_id)
            identifiers = context.xpath('.//*[local-name()="identifier"]')
            if len(identifiers) != 1 or (
                identifiers[0].get("scheme") != fact.entity_scheme
                or identifiers[0].text != fact.entity_identifier
                or fact.entity_identifier != source.scope.issuer_id
            ):
                raise _invalid("review original entity context differs")

            def period(local: str) -> date | None:
                values = context.xpath(".//*[local-name()=$local]", local=local)
                if len(values) > 1:
                    raise _invalid("review original period is ambiguous")
                return date.fromisoformat(values[0].text) if values else None

            if (period("startDate"), period("endDate"), period("instant")) != (
                fact.period_start,
                fact.period_end,
                fact.instant,
            ):
                raise _invalid("review original period differs")
            members = context.xpath('.//*[local-name()="explicitMember"]')
            dimensions = tuple(sorted((m.get("dimension"), m.text) for m in members))
            namespaces = tuple(
                sorted(
                    (
                        m.get("dimension"),
                        _namespace(m, m.get("dimension")),
                        _namespace(m, m.text),
                    )
                    for m in members
                )
            )
            if (
                context.xpath('.//*[local-name()="typedMember"]')
                or dimensions != fact.dimensions
                or namespaces != fact.dimension_namespace_uris
            ):
                raise _invalid("review original dimension context differs")
            unit = _one(root, "unit", node.get("unitRef", ""))
            measures = unit.xpath('.//*[local-name()="measure"]')
            if (
                len(measures) != 1
                or measures[0].text != fact.unit
                or unit.xpath('.//*[local-name()="divide"]')
            ):
                raise _invalid("review original unit differs or is unsupported")
            if (
                _namespace(measures[0], measures[0].text)
                != "http://www.xbrl.org/2003/iso4217"
            ):
                raise _invalid("review requires the original currency namespace")
        facts = {item.fact_id: item for item in review.facts}
        actual = facts.get(focus.fact_id)
        if (
            actual is None
            or actual.fact != focus.fact
            or actual.value != Decimal(focus.numeric_value)
        ):
            raise _invalid("review does not preserve the actual diagnostic focus")
        covered: set[str] = set()
        with localcontext() as context:
            context.prec = 4400
            for reconciliation in review.reconciliations:
                check_deadline()
                result = facts[reconciliation.result_fact_id]
                inputs = tuple(
                    (facts[term.fact_id], term.coefficient)
                    for term in reconciliation.terms
                )
                compatible = (
                    result.fact.unit,
                    result.fact.period_start,
                    result.fact.period_end,
                    result.fact.instant,
                )
                if any(
                    (
                        item.fact.unit,
                        item.fact.period_start,
                        item.fact.period_end,
                        item.fact.instant,
                    )
                    != compatible
                    for item, _ in inputs
                ):
                    raise _invalid(
                        "source reconciliation combines different units or periods"
                    )
                residual = (
                    sum(
                        (item.value * coefficient for item, coefficient in inputs),
                        Decimal(0),
                    )
                    - result.value
                )
                allowance = sum(
                    (
                        _uncertainty(item.raw_decimals) * abs(coefficient)
                        for item, coefficient in inputs
                    ),
                    _uncertainty(result.raw_decimals),
                )
                if (
                    reconciliation.residual != residual
                    or reconciliation.precision_allowance != allowance
                    or abs(residual) > allowance
                ):
                    raise _invalid(
                        "source reconciliation arithmetic or precision differs"
                    )
                covered.update(item.fact_id for item, _ in inputs)
                covered.add(result.fact_id)
        if focus.fact_id not in covered:
            raise _invalid("actual focus must be covered by source reconciliation")
    except (ValueError, InvalidOperation, etree.XMLSyntaxError) as error:
        raise _invalid("review original transcription is invalid") from error
    check_deadline()
