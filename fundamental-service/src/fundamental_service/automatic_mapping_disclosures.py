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
    DisclosedInstantAmountV1,
    DisclosedInstantDateV1,
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
OPTION_COST_DISCLOSURE_POLICY = "original-bound-dated-option-compensation-usd-v1"
_OPTION_COST = re.compile(
    r"(?:^|(?<=[.>]))[ \t\r\n\u00a0]*"
    rf"(?P<sentence>There was \$(?P<amount>{_AMOUNT}) of unrecognized "
    r"stock-based compensation as of (?P<month_day>[A-Z][a-z]+ [0-9]{1,2}), (?P<year>[0-9]{4}) "
    r"related to nonvested options, which we expect to recognize in the first "
    r"quarter of fiscal (?P<next_year>[0-9]{4})\.)"
)
# Classification pins for the complete NVE option note; amounts remain observations.
_OPTION_COST_ORIGINALS = {
    ("0000724910", "0001376474-23-000283"): (
        "26d95888105590690531f4b3c4da8ca910e6aa4e315f6372ed51c55459b0b05c",
        "1ce5d69c3a2b560110b3cfffba644b15125475ce3531a99bdc5a5f5fd35ef90e",
    ),
    ("0000724910", "0001376474-24-000214"): (
        "e337d87718577db631e61f5495c3c8f96304c0552161cb5054305967394c9dc6",
        "21c4ebca39e56c934edded6065b4ac78a0f451de96a540afe5d49726c53b01c1",
    ),
}


@dataclass(frozen=True)
class CompensationDisclosureSelection:
    rules: AccountingRoleRules | None
    selected: tuple[ParsedXbrlFactV1, ...]
    rejected: tuple[tuple[ParsedXbrlFactV1, str], ...]
    reason_codes: tuple[str, ...]


def select_option_compensation_disclosure(
    original: OriginalIssuerEvidenceV1, *, security_id: str | None = None
) -> CompensationDisclosureSelection:
    """Transcribe one registered option-cost balance, without approving inventory."""
    source = original.source
    entry = _OPTION_COST_ORIGINALS.get((source.cik, source.accession_number))
    if entry is None or source.content_hash != entry[0]:
        return CompensationDisclosureSelection(
            None, (), (), ("MAPPING_OPTION_COST_SCOPE_UNREVIEWED",)
        )
    if fact_semantic_digest(original.report) != entry[1]:
        return CompensationDisclosureSelection(
            None, (), (), ("MAPPING_OPTION_COST_SOURCE_MISMATCH",)
        )
    selected = []
    rejected = []
    reasons = set()
    periods = []
    for fact in sorted(original.report.facts, key=sha256_digest):
        if fact.concept != STOCK_COMPENSATION_DISCLOSURE:
            continue
        reason = _source_rejection(fact, original)
        matches = tuple(_OPTION_COST.finditer(fact.value)) if reason is None else ()
        if reason is None and len(matches) != 1:
            reason = "MAPPING_DISCLOSURE_SENTENCE_UNSUPPORTED"
        if reason is not None:
            rejected.append((fact, reason))
            reasons.add(reason)
            continue
        match = matches[0]
        instant = original.report_period_end
        if (
            instant is None
            or int(match["year"]) != instant.year
            or int(match["next_year"]) != instant.year + 1
        ):
            reason = "MAPPING_DISCLOSURE_PERIOD_MISMATCH"
            rejected.append((fact, reason))
            reasons.add(reason)
            continue
        quote = match["sentence"]
        start = match.start("sentence")
        symbol = match.start("amount") - 1
        try:
            dated = DisclosedInstantDateV1(
                period_end=instant,
                month_day_start=match.start("month_day") - start,
                month_day_token=match["month_day"],
                year_start=match.start("year") - start,
                year_token=match["year"],
            )
        except ValueError:
            reason = "MAPPING_DISCLOSURE_PERIOD_MISMATCH"
            rejected.append((fact, reason))
            reasons.add(reason)
            continue
        amount = DisclosedInstantAmountV1(
            parsed_fact_digest=sha256_digest(fact),
            quote_start=start,
            exact_quote=quote,
            amount_start=match.start("amount") - start,
            amount_token=match["amount"],
            scale_start=symbol,
            scale_token="$",
            scale=0,
            unit_start=symbol,
            unit_quote="$",
            reported_unit="iso4217:USD",
            reported_decimals=0,
            covered_classes=("total unrecognized compensation for nonvested options",),
            complete_role=True,
            date=dated,
        )
        selected.append(fact)
        periods.append(
            AccountingPeriodRuleV1(
                period=AccountingPeriodV1(period_end=instant, instant=True),
                disposition="disclosed",
                disclosed_amount=amount,
                rationale=OPTION_COST_DISCLOSURE_POLICY,
            )
        )
    if len(periods) != 1:
        reasons.add("MAPPING_OPTION_COST_DISCLOSURE_AMBIGUOUS")
    rules: AccountingRoleRules | None = None
    if not reasons:
        rules = IssuerAccountingRoleRuleSetV1(
            policy_version=OPTION_COST_DISCLOSURE_POLICY,
            normalized_field="equity_award_unrecognized_compensation",
            issuer_id=source.cik,
            accession_number=source.accession_number,
            raw_content_hash=source.content_hash,
            parser_input_hash=source.parser_input_hash,
            parser_fact_digest=entry[1],
            unit="iso4217:USD",
            currency="USD",
            periods=tuple(periods),
        )
        if security_id is not None:
            rules = AccountingRoleRuleSetV1.model_validate(
                {
                    **rules.model_dump(exclude={"protocol", "security_id"}),
                    "security_id": security_id,
                }
            )
    return CompensationDisclosureSelection(
        rules, tuple(selected), tuple(rejected), tuple(sorted(reasons))
    )


def select_stock_compensation_disclosure(
    original: OriginalIssuerEvidenceV1,
    *,
    security_id: str | None = None,
) -> CompensationDisclosureSelection:
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
    return CompensationDisclosureSelection(
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
