"""Bounded automatic transcription of explicit annual stock compensation expense."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .accounting_roles import (
    AccountingPeriodRuleV1,
    AccountingPeriodV1,
    AccountingRoleRules,
    AccountingRoleRuleSetV1,
    DisclosedAmountV1,
    IssuerAccountingRoleRuleSetV1,
)
from .arelle_parser import fact_semantic_digest, ParsedXbrlFactV1
from .original_issuer import OriginalIssuerEvidenceV1
from .serialization import sha256_digest


STOCK_COMPENSATION_DISCLOSURE = (
    "us-gaap:DisclosureOfCompensationRelatedCostsShareBasedPaymentsTextBlock"
)
STOCK_COMPENSATION_DISCLOSURE_POLICY = "explicit-annual-stock-compensation-usd-v1"
_AMOUNT = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
_EXPENSE = re.compile(
    r"(?:^|(?<=[.>]))[ \t\r\n\u00a0]*"
    r"(?P<sentence>Stock-based compensation expense was "
    rf"\$(?P<amount>{_AMOUNT}) in fiscal[ \u00a0]+(?P<year>[0-9]{{4}}) "
    rf"and \$(?P<prior>{_AMOUNT}) in fiscal[ \u00a0]+(?P<prior_year>[0-9]{{4}})\.)"
)


@dataclass(frozen=True)
class StockCompensationDisclosureSelection:
    rules: AccountingRoleRules | None
    selected: tuple[ParsedXbrlFactV1, ...]
    rejected: tuple[tuple[ParsedXbrlFactV1, str], ...]
    reason_codes: tuple[str, ...]


def select_stock_compensation_disclosure(
    original: OriginalIssuerEvidenceV1,
    *,
    security_id: str | None = None,
) -> StockCompensationDisclosureSelection:
    """Admit only a complete exact sentence for the text fact's own annual period."""
    selected: list[tuple[ParsedXbrlFactV1, AccountingPeriodRuleV1]] = []
    rejected = []
    reasons = []
    if any(
        re.search(
            r"\bin\s+(?:thousands?|millions?|billions?)\b",
            re.sub(r"<[^>]*>", " ", fact.value),
            re.IGNORECASE,
        )
        for fact in original.report.facts
        if not fact.is_numeric
    ):
        reasons.append("MAPPING_DISCLOSURE_SCALE_UNRESOLVED")
    for fact in sorted(original.report.facts, key=sha256_digest):
        if fact.concept != STOCK_COMPENSATION_DISCLOSURE:
            continue
        reason = _source_rejection(fact, original)
        matches = tuple(_EXPENSE.finditer(fact.value)) if reason is None else ()
        if reason is None and len(matches) != 1:
            reason = "MAPPING_DISCLOSURE_SENTENCE_UNSUPPORTED"
            reasons.append(reason)
        if reason is not None:
            rejected.append((fact, reason))
            continue
        match = matches[0]
        assert fact.period_start is not None and fact.period_end is not None
        if (
            int(match["year"]) != fact.period_end.year
            or int(match["prior_year"]) != fact.period_end.year - 1
        ):
            reason = "MAPPING_DISCLOSURE_PERIOD_MISMATCH"
            rejected.append((fact, reason))
            reasons.append(reason)
            continue
        quote = match["sentence"]
        amount_start = match.start("amount") - match.start("sentence")
        symbol_start = match.start("amount") - 1
        rule = AccountingPeriodRuleV1(
            period=AccountingPeriodV1(
                period_start=fact.period_start, period_end=fact.period_end
            ),
            disposition="disclosed",
            disclosed_amount=DisclosedAmountV1(
                parsed_fact_digest=sha256_digest(fact),
                quote_start=match.start("sentence"),
                exact_quote=quote,
                amount_start=amount_start,
                amount_token=match["amount"],
                scale_start=symbol_start,
                scale_token="$",
                scale=0,
                unit_start=symbol_start,
                unit_quote="$",
                reported_unit="iso4217:USD",
                reported_decimals=0,
                covered_classes=("total stock-based compensation expense",),
                complete_role=True,
            ),
            rationale=STOCK_COMPENSATION_DISCLOSURE_POLICY,
        )
        selected.append((fact, rule))
    if not selected:
        reasons.append("MAPPING_NO_ELIGIBLE_OBSERVATIONS")
    if len({rule.period for _, rule in selected}) > 1:
        reasons.append("MAPPING_DISCLOSURE_PERIOD_MISMATCH")
    if (
        len(
            {
                rule.disclosed_amount.amount_token
                for _, rule in selected
                if rule.disclosed_amount is not None
            }
        )
        > 1
    ):
        reasons.append("MAPPING_OBSERVATION_CONFLICT")
    rules: AccountingRoleRules | None = None
    if not reasons:
        rules = IssuerAccountingRoleRuleSetV1(
            policy_version=STOCK_COMPENSATION_DISCLOSURE_POLICY,
            normalized_field="stock_based_compensation",
            issuer_id=original.source.cik,
            accession_number=original.source.accession_number,
            raw_content_hash=original.source.content_hash,
            parser_input_hash=original.source.parser_input_hash,
            parser_fact_digest=fact_semantic_digest(original.report),
            unit="iso4217:USD",
            currency="USD",
            periods=(selected[0][1],),
        )
        if security_id is not None:
            rules = AccountingRoleRuleSetV1.model_validate(
                {
                    **rules.model_dump(exclude={"protocol", "security_id"}),
                    "security_id": security_id,
                }
            )
    return StockCompensationDisclosureSelection(
        rules=rules,
        selected=tuple(fact for fact, _ in selected),
        rejected=tuple(rejected),
        reason_codes=tuple(sorted(set(reasons))),
    )


def _source_rejection(
    fact: ParsedXbrlFactV1, original: OriginalIssuerEvidenceV1
) -> str | None:
    if not re.fullmatch(
        r"http://(?:fasb\.org|xbrl\.us)/us-gaap/\d{4}(?:-\d{2}-\d{2})?",
        fact.namespace_uri or "",
    ):
        return "MAPPING_NAMESPACE_UNSUPPORTED"
    if (
        fact.entity_scheme != "http://www.sec.gov/CIK"
        or not re.fullmatch(r"[0-9]{1,10}", fact.entity_identifier or "")
        or int(fact.entity_identifier or "0") != int(original.source.cik)
    ):
        return "MAPPING_ISSUER_MISMATCH"
    if (
        fact.dimensions
        or fact.consolidation_scope != "consolidated"
        or fact.security_scope not in {"issuer", "unspecified"}
    ):
        return "MAPPING_SCOPE_UNSUPPORTED"
    if fact.is_numeric or fact.unit is not None:
        return "MAPPING_UNIT_UNSUPPORTED"
    if (
        fact.instant is not None
        or fact.period_start is None
        or fact.period_end is None
        or fact.period_end != original.report_period_end
        or not 330 <= (fact.period_end - fact.period_start).days <= 371
        or not any(
            marker.concept == "dei:DocumentPeriodEndDate"
            and marker.period_start == fact.period_start
            and marker.period_end == fact.period_end
            for marker in original.report.facts
        )
    ):
        return "MAPPING_PERIOD_UNSUPPORTED"
    return None
