from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum, auto
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from lxml import etree
from pydantic import ConfigDict, Field

from .arelle_parser import ParsedXbrlFactV1, fact_semantic_digest
from .contracts import StrictModel
from .dqc_applicability import _assertion_dates, _document_dates
from .fiscal_candidate_contracts import FiscalSourceUseScopeV1
from .fiscal_classification_contracts import (
    FiscalReconciliationTermV1,
    FiscalReviewFactV1,
    FiscalSourceAccountingReviewV1,
    FiscalSourceReconciliationV1,
)
from .fiscal_classification_source import FiscalClassificationSource
from .fiscal_statement_mapping import (
    fiscal_display_profile_digest,
    fiscal_mapping_policy_digest,
)
from .fiscal_validation_contracts import FiscalValidationCompleteRefusedV1
from .ingestion import read_sec_xbrl_archive
from .parser_action_contracts import ParserActionResultV2
from .parser_computation import execution_validation_evidence
from .serialization import sha256_digest
from .snapshots import SnapshotError

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DisclosureRole = Literal["balance_sheet", "investments", "derivatives"]
AccountingFactRole = Literal[
    "investment_debt",
    "investment_equity",
    "investment_cash",
    "investment_derivative",
    "investment_total",
    "balance_cash",
    "balance_investments",
    "balance_combined",
    "derivative_gross",
    "derivative_offset",
    "derivative_collateral",
    "derivative_net",
    "derivative_short_term",
    "derivative_current",
    "derivative_noncurrent",
    "derivative_location_total",
]
AccountingPresentation = Literal["positive", "negative", "deduction"]
AccountingPredicate = Literal[
    "original_disclosure_roles",
    "note4_note5_crossreference",
    "cross_note_signed_classification",
    "role_specific_contexts",
    "complete_disclosed_bridges",
    "counterevidence_excluded",
]
AccountingRefusalReason = Literal[
    "unsupported_source",
    "source_scope_mismatch",
    "source_hash_mismatch",
    "unsupported_diagnostic",
    "ambiguous_disclosure",
    "missing_disclosure",
    "contradictory_disclosure",
    "unsupported_numeric",
    "unsupported_presentation",
    "fact_context_mismatch",
    "focus_mismatch",
    "incomplete_bridge",
    "reconciliation_mismatch",
]


class _AccountingPolicyModel(StrictModel):
    model_config = ConfigDict(frozen=True, strict=True)


class FiscalAccountingPolicyIdentityV1(_AccountingPolicyModel):
    policy_id: str
    version: int = Field(ge=1)
    definition_sha256: Digest
    executable_sha256: Digest


PlainLocationRole = Literal[
    "derivative_current_liability", "derivative_noncurrent_liability"
]


@dataclass(frozen=True)
class _FactRole:
    role: AccountingFactRole
    disclosure: DisclosureRole
    row: str
    concept: str
    dimensions: tuple[tuple[str, str], ...] = ()
    presentation: AccountingPresentation = "positive"

    @property
    def tagged_dimensions(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                ("us-gaap:" + axis, "us-gaap:" + member)
                for axis, member in self.dimensions
            )
        )

    def has_expected_sign(self, raw_sign: str | None, value: Decimal) -> bool:
        if self.presentation == "negative":
            return raw_sign == "-" and value < 0
        if self.presentation == "deduction":
            return raw_sign is None and value > 0
        return raw_sign is None and value >= 0

    def displayed_amount(self, lexical: str) -> str:
        return lexical if self.presentation == "positive" else "( " + lexical


@dataclass(frozen=True)
class _Disclosure:
    role: DisclosureRole
    heading: str
    columns: tuple[str, ...]
    date_mode: str
    required_title: str | None
    selected_column: str
    amount_column: int
    end_heading: str
    units_label: str = "(In millions)"


@dataclass(frozen=True)
class _PlainZeroRole:
    role: PlainLocationRole
    row: str
    disclosure: DisclosureRole = "derivatives"


@dataclass(frozen=True)
class _Bridge:
    description: str
    inputs: tuple[tuple[AccountingFactRole, int], ...]
    output: AccountingFactRole
    plain_zeros: tuple[_PlainZeroRole, ...] = ()


@dataclass(frozen=True)
class _Policy:
    policy_id: str
    version: int
    issuer: str
    accession: str
    primary: str
    archive_sha256: str
    primary_sha256: str
    instant: date
    current_label: str
    comparative_label: str
    diagnostic: str
    footnote_text: str
    disclosures: tuple[_Disclosure, ...]
    facts: tuple[_FactRole, ...]
    bridges: tuple[_Bridge, ...]
    limitations: tuple[str, ...]
    link_role: str = "http://www.xbrl.org/2003/role/link"
    arcrole: str = "http://www.xbrl.org/2003/arcrole/fact-footnote"
    endpoint_columns: tuple[tuple[int, str], ...] = (
        (17, "DerivativeAssets"),
        (21, "CashAndCashEquivalentsAtCarryingValue"),
        (25, "ShortTermInvestments"),
        (29, "LongTermInvestments"),
    )
    comparative_instant: date = date(2024, 6, 30)
    exact_pairs: tuple[tuple[AccountingFactRole, AccountingFactRole], ...] = (
        ("investment_derivative", "derivative_short_term"),
        ("derivative_net", "derivative_location_total"),
    )
    max_outer: int = 9 * 1024 * 1024
    max_validation: int = 6 * 1024 * 1024
    max_witness: int = 32 * 1024
    max_scope: int = 96 * 1024
    max_capsule_archive: int = 384 * 1024
    max_claim: int = 256 * 1024
    max_scalar_bytes: int = 1024 * 1024
    max_depth: int = 64
    max_json_nodes: int = 131_072
    replay_seconds: float = 10.0
    max_primary_bytes: int = 6 * 1024 * 1024
    max_archive_bytes: int = 32 * 1024 * 1024
    max_nodes: int = 200_000
    max_tables: int = 256
    max_rows: int = 256
    max_cells: int = 128
    max_numeric_digits: int = 1000
    max_scale: int = 1000
    max_report_facts: int = 5000
    max_findings: int = 256
    max_actions: int = 32
    max_responses: int = 64
    max_observations: int = 128


_POLICY = _Policy(
    policy_id="msft-20240930-derivative-source-as-disclosed",
    version=3,
    issuer="0000789019",
    accession="0000950170-24-118967",
    primary="msft-20240930.htm",
    archive_sha256="c2633b021dcd9f36160b732de59abf30dbe16fa234de8e92dc7583f312e5b5a5",
    primary_sha256="3b63f34ecf33818dde9b8cfcdbc9074399e4578e1b971a7832dbc5d9883cf501",
    instant=date(2024, 9, 30),
    current_label="September 30, 2024",
    comparative_label="June 30, 2024",
    diagnostic="DQC.US.0015.5970",
    footnote_text=(
        "Refer to Note 5 – Derivatives for further information on the fair value "
        "of our derivative instruments."
    ),
    disclosures=(
        _Disclosure(
            "balance_sheet",
            "BALANCE SHEETS",
            (),
            "columns",
            None,
            "September 30, 2024",
            3,
            "CASH FLOWS STATEMENTS",
            units_label="(In millions) (Unaudited)",
        ),
        _Disclosure(
            "investments",
            "NOTE 4 — INVESTMENTS",
            (
                "Fair Value Level",
                "Adjusted Cost Basis",
                "Unrealized Gains",
                "Unrealized Losses",
                "Recorded Basis",
                "Cash and Cash Equivalents",
                "Short-term Investments",
                "Equity and Other Investments",
            ),
            "table",
            "The components of investments were as follows:",
            "Short-term Investments",
            25,
            "Unrealized Losses on Debt Investments",
        ),
        _Disclosure(
            "derivatives",
            "NOTE 5 — DERIVATIVES",
            (
                "Derivative Assets",
                "Derivative Liabilities",
                "Derivative Assets",
                "Derivative Liabilities",
            ),
            "columns",
            "Fair Values of Derivative Instruments",
            "Derivative Assets",
            3,
            "The following table presents the fair value of our derivatives instruments on a gross basis:",
        ),
    ),
    facts=(
        _FactRole(
            "investment_debt",
            "investments",
            "Total debt investments",
            "ShortTermInvestments",
            (("FairValueByAssetClassAxis", "DebtSecuritiesMember"),),
        ),
        _FactRole(
            "investment_equity",
            "investments",
            "Total equity investments",
            "ShortTermInvestments",
            (("FinancialInstrumentAxis", "EquitySecuritiesMember"),),
        ),
        _FactRole(
            "investment_cash",
            "investments",
            "Cash",
            "ShortTermInvestments",
            (("FinancialInstrumentAxis", "CashMember"),),
        ),
        _FactRole(
            "investment_derivative",
            "investments",
            "Derivatives, net (a)",
            "ShortTermInvestments",
            (("FinancialInstrumentAxis", "DerivativeMember"),),
            "negative",
        ),
        _FactRole("investment_total", "investments", "Total", "ShortTermInvestments"),
        _FactRole(
            "balance_cash",
            "balance_sheet",
            "Cash and cash equivalents",
            "CashAndCashEquivalentsAtCarryingValue",
        ),
        _FactRole(
            "balance_investments",
            "balance_sheet",
            "Short-term investments",
            "ShortTermInvestments",
        ),
        _FactRole(
            "balance_combined",
            "balance_sheet",
            "Total cash, cash equivalents, and short-term investments",
            "CashCashEquivalentsAndShortTermInvestments",
        ),
        _FactRole(
            "derivative_gross",
            "derivatives",
            "Gross amounts of derivatives",
            "DerivativeAssetFairValueGrossAssetIncludingNotSubjectToMasterNettingArrangement",
        ),
        _FactRole(
            "derivative_offset",
            "derivatives",
            "Gross amounts of derivatives offset in the balance sheets",
            "DerivativeAssetFairValueGrossLiability",
            presentation="deduction",
        ),
        _FactRole(
            "derivative_collateral",
            "derivatives",
            "Cash collateral received",
            "DerivativeCollateralRightToReclaimCash",
        ),
        _FactRole(
            "derivative_net",
            "derivatives",
            "Net amounts of derivatives",
            "DerivativeAssets",
        ),
        _FactRole(
            "derivative_short_term",
            "derivatives",
            "Short-term investments",
            "DerivativeAssets",
            (("BalanceSheetLocationAxis", "ShortTermInvestmentsMember"),),
            "negative",
        ),
        _FactRole(
            "derivative_current",
            "derivatives",
            "Other current assets",
            "DerivativeAssets",
            (("BalanceSheetLocationAxis", "OtherCurrentAssetsMember"),),
        ),
        _FactRole(
            "derivative_noncurrent",
            "derivatives",
            "Other long-term assets",
            "DerivativeAssets",
            (("BalanceSheetLocationAxis", "OtherNoncurrentAssetsMember"),),
        ),
        _FactRole(
            "derivative_location_total", "derivatives", "Total", "DerivativeAssets"
        ),
    ),
    bridges=(
        _Bridge(
            "Note 4 complete short-term-investment classes",
            (
                ("investment_debt", 1),
                ("investment_equity", 1),
                ("investment_cash", 1),
                ("investment_derivative", 1),
            ),
            "investment_total",
        ),
        _Bridge(
            "Note 4 short-term investments to consolidated balance sheet",
            (("investment_total", 1),),
            "balance_investments",
        ),
        _Bridge(
            "Consolidated cash plus short-term investments",
            (("balance_cash", 1), ("balance_investments", 1)),
            "balance_combined",
        ),
        _Bridge(
            "Note 5 derivative assets gross less offset plus collateral",
            (
                ("derivative_gross", 1),
                ("derivative_offset", -1),
                ("derivative_collateral", 1),
            ),
            "derivative_net",
        ),
        _Bridge(
            "Note 5 complete derivative asset balance-sheet locations",
            (
                ("derivative_short_term", 1),
                ("derivative_current", 1),
                ("derivative_noncurrent", 1),
            ),
            "derivative_location_total",
            (
                _PlainZeroRole(
                    "derivative_current_liability", "Other current liabilities"
                ),
                _PlainZeroRole(
                    "derivative_noncurrent_liability", "Other long-term liabilities"
                ),
            ),
        ),
    ),
    limitations=(
        "Only the exact original accession and diagnostic are evaluated, with the supplied exact source-use scope and actual execution identities retained.",
        "This machine policy supports issuer presentation as disclosed. US GAAP tagging remains unresolved. The raw complete_refused outcome, error rule severity, warning and active blocking finding remain unchanged.",
        "No materiality, false-positive, GAAP certification, official waiver, mapping approval, candidate approval, display release or valuation permission is inferred.",
        "Different dimensions are compared only under the disclosed investment-class and balance-sheet-location roles. Comparative periods and amended or changed originals are unsupported.",
        "The pure evaluation authenticates no actor, signature, current grant or epoch. Production independence and separate release require their owning verifiers and actual independent review of this policy.",
    ),
)


def source_accounting_policy_identity() -> FiscalAccountingPolicyIdentityV1:
    paths = (
        Path(__file__),
        Path(__file__).with_name("fiscal_source_accounting_policy_contracts.py"),
    )
    try:
        executable = tuple(
            hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
        )
    except OSError as error:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_RESOURCE_UNAVAILABLE",
            "Accounting evaluator source cannot be identified",
        ) from error
    return FiscalAccountingPolicyIdentityV1(
        policy_id=_POLICY.policy_id,
        version=_POLICY.version,
        definition_sha256=sha256_digest(
            (
                asdict(_POLICY),
                {
                    key: tuple(asdict(row) for row in rows)
                    for key, rows in _ROW_GRAMMAR.items()
                },
                asdict(_PRESENTATION_GRAMMAR),
            )
        ),
        executable_sha256=sha256_digest(executable),
    )


def _uncertainty(decimals: str) -> Decimal:
    return Decimal(0) if decimals == "INF" else Decimal(5).scaleb(-int(decimals) - 1)


def _reconciliation(
    bridge: _Bridge, facts: dict[AccountingFactRole, FiscalReviewFactV1]
) -> FiscalSourceReconciliationV1:
    output = facts[bridge.output]
    with localcontext() as context:
        context.prec = 4400
        residual = (
            sum(
                (
                    facts[role].value * coefficient
                    for role, coefficient in bridge.inputs
                ),
                Decimal(0),
            )
            - output.value
        )
        allowance = sum(
            (
                _uncertainty(facts[role].raw_decimals) * abs(coefficient)
                for role, coefficient in bridge.inputs
            ),
            _uncertainty(output.raw_decimals),
        )
        return FiscalSourceReconciliationV1(
            description=bridge.description,
            terms=tuple(
                FiscalReconciliationTermV1(
                    fact_id=facts[role].fact_id, coefficient=coefficient
                )
                for role, coefficient in bridge.inputs
            ),
            result_fact_id=output.fact_id,
            residual=residual,
            precision_allowance=allowance,
        )


class FiscalDisclosureLocatorV1(_AccountingPolicyModel):
    source_id: str | None
    xpath: str
    source_line: int = Field(ge=1)
    sha256: Digest
    text: str = Field(max_length=4096)


class FiscalAccountingPlainZeroV1(_AccountingPolicyModel):
    role: PlainLocationRole
    heading: FiscalDisclosureLocatorV1
    row_sha256: Digest
    region_sha256: Digest
    row_label: FiscalDisclosureLocatorV1
    column_header: FiscalDisclosureLocatorV1
    date_header: FiscalDisclosureLocatorV1
    cell: FiscalDisclosureLocatorV1
    logical_column: int = Field(ge=0)
    table_sha256: Digest


class FiscalAccountingSemanticFactV1(_AccountingPolicyModel):
    role: AccountingFactRole
    transcription: FiscalReviewFactV1
    original_fact: FiscalDisclosureLocatorV1
    disclosure: DisclosureRole
    heading: FiscalDisclosureLocatorV1
    row_label: FiscalDisclosureLocatorV1
    column_header: FiscalDisclosureLocatorV1
    date_header: FiscalDisclosureLocatorV1
    cell: FiscalDisclosureLocatorV1
    context: FiscalDisclosureLocatorV1
    unit: FiscalDisclosureLocatorV1
    logical_column: int = Field(ge=0)
    region_sha256: Digest
    presented_sign: AccountingPresentation


class FiscalAccountingPredicateV1(_AccountingPolicyModel):
    predicate: AccountingPredicate
    supports: str
    falsified_by: str
    fact_roles: tuple[AccountingFactRole, ...]
    locators: tuple[FiscalDisclosureLocatorV1, ...]


class FiscalAccountingCounterevidenceScanV1(_AccountingPolicyModel):
    disclosure: DisclosureRole
    candidates: tuple[FiscalDisclosureLocatorV1, ...]
    row_kinds: tuple[str, ...]
    selected_table_sha256: Digest
    observed_date_headers: tuple[FiscalDisclosureLocatorV1, ...]
    competing_columns: tuple[FiscalDisclosureLocatorV1, ...]
    examined_numeric_cells: int = Field(ge=1)


class FocusFootnote(_AccountingPolicyModel):
    focus_id: str
    relationship: FiscalDisclosureLocatorV1
    from_refs: tuple[str, ...]
    to_ref: str
    footnote: FiscalDisclosureLocatorV1
    container: FiscalDisclosureLocatorV1
    link_role: str
    arcrole: str


class _VerdictBase(_AccountingPolicyModel):
    policy: FiscalAccountingPolicyIdentityV1
    source_evidence_sha256: Digest
    witness_sha256: Digest
    scope_sha256: Digest
    archive_sha256: Digest
    primary_sha256: Digest | None


class AccountingSupport(_VerdictBase):
    kind: Literal["supported"] = "supported"
    tagged: tuple[FiscalAccountingSemanticFactV1, ...]
    plain_zeros: tuple[FiscalAccountingPlainZeroV1, ...]
    link: FocusFootnote
    tables: tuple[FiscalAccountingCounterevidenceScanV1, ...]
    bridges: tuple[FiscalSourceReconciliationV1, ...]

    def _review(self, scope: FiscalSourceUseScopeV1) -> FiscalSourceAccountingReviewV1:
        if scope.scope_digest != self.scope_sha256:
            raise ValueError(
                "Accounting review scope differs from the evaluated source"
            )
        return FiscalSourceAccountingReviewV1(
            scope=scope,
            facts=tuple(item.transcription for item in self.tagged),
            reconciliations=self.bridges,
            limitations=_POLICY.limitations,
        )

    def explanations(self) -> tuple[FiscalAccountingPredicateV1, ...]:
        facts = tuple(item.role for item in self.tagged)
        return (
            FiscalAccountingPredicateV1(
                predicate="original_disclosure_roles",
                supports="Current-date original headings, row captions and logical column spans select issuer-disclosed roles, including both genuine zero components.",
                falsified_by="Missing, duplicated, renamed or moved heading, row, column or date; an omitted or added disclosed class or location.",
                fact_roles=tuple(facts),
                locators=tuple(dict.fromkeys(item.heading for item in self.tagged)),
            ),
            FiscalAccountingPredicateV1(
                predicate="note4_note5_crossreference",
                supports="Note 4 Derivatives, net (a) is linked by the original fact-footnote relationship to the Note 5 derivative fair-values cross-reference.",
                falsified_by="Missing footnote (a), different note destination, relationship source or destination, or a cross-reference outside Note 4.",
                fact_roles=("investment_derivative", "derivative_short_term"),
                locators=(self.link.footnote, self.link.relationship),
            ),
            FiscalAccountingPredicateV1(
                predicate="cross_note_signed_classification",
                supports="The signed Note 4 short-term-investment derivative agrees with the independently disclosed Note 5 derivative asset classified in Short-term investments, and both Note 5 net totals agree.",
                falsified_by="Different sign, balance-sheet location, date, tagged concept or disagreeing cross-note amount or net total, even if some equation balances.",
                fact_roles=(
                    "investment_derivative",
                    "derivative_short_term",
                    "derivative_net",
                    "derivative_location_total",
                ),
                locators=(),
            ),
            FiscalAccountingPredicateV1(
                predicate="role_specific_contexts",
                supports="Note 4 investment classes use their disclosed financial-instrument or asset-class axis; Note 5 uses the distinct balance-sheet-location axis; consolidated totals are unsegmented. All are original USD instant contexts for the same issuer and date.",
                falsified_by="Generic dimension equality, substituted dimension or namespace, another issuer, unit, duration, date or consolidated/segmented role.",
                fact_roles=tuple(facts),
                locators=(),
            ),
            FiscalAccountingPredicateV1(
                predicate="complete_disclosed_bridges",
                supports="The five bridges use the tagged amounts at source precision. The Note 5 locations also include both untagged liability rows explicitly displaying zero; those cells contribute no tagged precision. Offset preserves its positive XBRL value with a negative coefficient because the disclosure presents a deduction.",
                falsified_by="Omitted zero or negative component, balancing plug, unsupported sign, insufficient precision or residual above the sum of source half-units weighted by absolute coefficient plus output.",
                fact_roles=tuple(facts),
                locators=tuple(zero.cell for zero in self.plain_zeros),
            ),
            FiscalAccountingPredicateV1(
                predicate="counterevidence_excluded",
                supports="All candidate disclosures, current/comparative date headers, competing asset/liability and cash/investment columns, and complete class/location rows are scanned before accepting the selected current roles.",
                falsified_by="Multiple current candidate tables or numeric cells, earlier-date substitution, asset/liability column substitution or unexplained class/location row.",
                fact_roles=tuple(facts),
                locators=(),
            ),
        )


class AccountingRefusal(_VerdictBase):
    kind: Literal["refused"] = "refused"
    reason: AccountingRefusalReason
    detail: str


AccountingVerdict = Annotated[
    AccountingSupport | AccountingRefusal, Field(discriminator="kind")
]


@dataclass(frozen=True)
class EvaluatedSourceAccounting:
    _source: FiscalClassificationSource
    result: AccountingSupport | AccountingRefusal

    def review(self) -> FiscalSourceAccountingReviewV1 | None:
        if isinstance(self.result, AccountingSupport):
            return self.result._review(self._source.scope)
        return None


_XHTML = "http://www.w3.org/1999/xhtml"
_SVG = "http://www.w3.org/2000/svg"
_IX = "http://www.xbrl.org/2013/inlineXBRL"
_XBRLI = "http://www.xbrl.org/2003/instance"
_XBRLDI = "http://xbrl.org/2006/xbrldi"
_ISO4217 = "http://www.xbrl.org/2003/iso4217"
_GAAP = "http://fasb.org/us-gaap/2024"


@dataclass(frozen=True)
class _RowRule:
    kind: str
    caption: str
    literals: tuple[tuple[int, int, str], ...] = ()
    amounts: tuple[int, ...] = ()
    plain: tuple[int, ...] = ()
    currency: tuple[int, ...] = ()
    caption_facts: tuple[str, ...] = ()


_ROW_GRAMMAR: Mapping[str, tuple[_RowRule, ...]] = MappingProxyType(
    {
        "balance_sheet": (
            _RowRule("header", "(In millions) (Unaudited)"),
            _RowRule(
                "date",
                "",
                literals=((2, 4, "September 30, 2024"), (6, 8, "June 30, 2024")),
            ),
            _RowRule("section", "Assets"),
            _RowRule("section", "Current assets:"),
            _RowRule(
                "detail", "Cash and cash equivalents", amounts=(3, 7), currency=(2, 6)
            ),
            _RowRule("detail", "Short-term investments", amounts=(3, 7)),
            _RowRule(
                "total",
                "Total cash, cash equivalents, and short-term investments",
                amounts=(3, 7),
            ),
            _RowRule(
                "detail",
                "Accounts receivable, net of allowance for doubtful accounts of $ 647 and $ 830",
                amounts=(3, 7),
                caption_facts=(
                    "us-gaap:AllowanceForDoubtfulAccountsReceivableCurrent",
                    "us-gaap:AllowanceForDoubtfulAccountsReceivableCurrent",
                ),
            ),
            _RowRule("detail", "Inventories", amounts=(3, 7)),
            _RowRule("detail", "Other current assets", amounts=(3, 7)),
            _RowRule("total", "Total current assets", amounts=(3, 7)),
            _RowRule(
                "detail",
                "Property and equipment, net of accumulated depreciation of $ 80,517 and $ 76,421",
                amounts=(3, 7),
                caption_facts=(
                    "us-gaap:AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
                    "us-gaap:AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
                ),
            ),
            _RowRule("detail", "Operating lease right-of-use assets", amounts=(3, 7)),
            _RowRule("detail", "Equity and other investments", amounts=(3, 7)),
            _RowRule("detail", "Goodwill", amounts=(3, 7)),
            _RowRule("detail", "Intangible assets, net", amounts=(3, 7)),
            _RowRule("detail", "Other long-term assets", amounts=(3, 7)),
            _RowRule("total", "Total assets", amounts=(3, 7), currency=(2, 6)),
            _RowRule("section", "Liabilities and stockholders’ equity"),
            _RowRule("section", "Current liabilities:"),
            _RowRule("detail", "Accounts payable", amounts=(3, 7), currency=(2, 6)),
            _RowRule("detail", "Short-term debt", amounts=(3, 7)),
            _RowRule("detail", "Current portion of long-term debt", amounts=(3, 7)),
            _RowRule("detail", "Accrued compensation", amounts=(3, 7)),
            _RowRule("detail", "Short-term income taxes", amounts=(3, 7)),
            _RowRule("detail", "Short-term unearned revenue", amounts=(3, 7)),
            _RowRule("detail", "Other current liabilities", amounts=(3, 7)),
            _RowRule("total", "Total current liabilities", amounts=(3, 7)),
            _RowRule("detail", "Long-term debt", amounts=(3, 7)),
            _RowRule("detail", "Long-term income taxes", amounts=(3, 7)),
            _RowRule("detail", "Long-term unearned revenue", amounts=(3, 7)),
            _RowRule("detail", "Deferred income taxes", amounts=(3, 7)),
            _RowRule("detail", "Operating lease liabilities", amounts=(3, 7)),
            _RowRule("detail", "Other long-term liabilities", amounts=(3, 7)),
            _RowRule("total", "Total liabilities", amounts=(3, 7)),
            _RowRule("section", "Commitments and contingencies"),
            _RowRule("section", "Stockholders’ equity:"),
            _RowRule(
                "detail",
                "Common stock and paid-in capital – shares authorized 24,000 ; outstanding 7,436 and 7,434",
                amounts=(3, 7),
                caption_facts=(
                    "us-gaap:CommonStockSharesAuthorized",
                    "us-gaap:CommonStockSharesAuthorized",
                    "us-gaap:CommonStockSharesOutstanding",
                    "us-gaap:CommonStockSharesOutstanding",
                ),
            ),
            _RowRule("detail", "Retained earnings", amounts=(3, 7)),
            _RowRule("detail", "Accumulated other comprehensive loss", amounts=(3, 7)),
            _RowRule("total", "Total stockholders’ equity", amounts=(3, 7)),
            _RowRule(
                "total",
                "Total liabilities and stockholders’ equity",
                amounts=(3, 7),
                currency=(2, 6),
            ),
        ),
        "investments": (
            _RowRule(
                "header",
                "(In millions)",
                literals=(
                    (2, 3, "Fair Value Level"),
                    (4, 6, "Adjusted Cost Basis"),
                    (8, 10, "Unrealized Gains"),
                    (12, 14, "Unrealized Losses"),
                    (16, 18, "Recorded Basis"),
                    (20, 22, "Cash and Cash Equivalents"),
                    (24, 26, "Short-term Investments"),
                    (28, 30, "Equity and Other Investments"),
                ),
            ),
            _RowRule("date", "September 30, 2024"),
            _RowRule(
                "section",
                "Changes in Fair Value Recorded in Other Comprehensive Income",
            ),
            _RowRule(
                "detail",
                "Commercial paper",
                literals=((2, 3, "Level 2"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
                currency=(4, 8, 12, 16, 20, 24, 28),
            ),
            _RowRule(
                "detail",
                "Certificates of deposit",
                literals=((2, 3, "Level 2"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "detail",
                "U.S. government securities",
                literals=((2, 3, "Level 1"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "detail",
                "U.S. agency securities",
                literals=((2, 3, "Level 2"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "detail",
                "Foreign government bonds",
                literals=((2, 3, "Level 2"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "detail",
                "Mortgage- and asset-backed securities",
                literals=((2, 3, "Level 2"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "detail",
                "Corporate notes and bonds",
                literals=((2, 3, "Level 2"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "detail",
                "Corporate notes and bonds",
                literals=((2, 3, "Level 3"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "detail",
                "Municipal securities",
                literals=((2, 3, "Level 2"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "detail",
                "Municipal securities",
                literals=((2, 3, "Level 3"),),
                amounts=(5, 9, 13, 17, 21, 25, 29),
            ),
            _RowRule(
                "total",
                "Total debt investments",
                amounts=(5, 9, 13, 17, 21, 25, 29),
                currency=(4, 8, 12, 16, 20, 24, 28),
            ),
            _RowRule("section", "Changes in Fair Value Recorded in Net Income"),
            _RowRule(
                "detail",
                "Equity investments",
                literals=((2, 3, "Level 1"),),
                amounts=(17, 21, 25, 29),
                currency=(16, 20, 24, 28),
            ),
            _RowRule(
                "detail",
                "Equity investments",
                literals=((2, 3, "Other"),),
                amounts=(17, 21, 25, 29),
            ),
            _RowRule(
                "total",
                "Total equity investments",
                amounts=(17, 21, 25, 29),
                currency=(16, 20, 24, 28),
            ),
            _RowRule(
                "detail", "Cash", amounts=(17, 21, 25, 29), currency=(16, 20, 24, 28)
            ),
            _RowRule("detail", "Derivatives, net (a)", amounts=(17, 21, 25, 29)),
            _RowRule(
                "total", "Total", amounts=(17, 21, 25, 29), currency=(16, 20, 24, 28)
            ),
        ),
        "derivatives": (
            _RowRule(
                "header",
                "(In millions)",
                literals=(
                    (2, 4, "Derivative Assets"),
                    (7, 8, "Derivative Liabilities"),
                    (10, 12, "Derivative Assets"),
                    (14, 16, "Derivative Liabilities"),
                ),
            ),
            _RowRule(
                "date",
                "",
                literals=((2, 8, "September 30, 2024"), (10, 16, "June 30, 2024")),
            ),
            _RowRule("section", "Designated as Hedging Instruments"),
            _RowRule(
                "detail",
                "Foreign exchange contracts",
                amounts=(3, 7, 11, 15),
                currency=(2, 6, 10, 14),
            ),
            _RowRule("detail", "Interest rate contracts", amounts=(3, 7, 11, 15)),
            _RowRule("section", "Not Designated as Hedging Instruments"),
            _RowRule("detail", "Foreign exchange contracts", amounts=(3, 7, 11, 15)),
            _RowRule("detail", "Equity contracts", amounts=(3, 7, 11, 15)),
            _RowRule("detail", "Other contracts", amounts=(3, 7, 11, 15)),
            _RowRule("total", "Gross amounts of derivatives", amounts=(3, 7, 11, 15)),
            _RowRule(
                "total",
                "Gross amounts of derivatives offset in the balance sheets",
                amounts=(3, 7, 11, 15),
            ),
            _RowRule("detail", "Cash collateral received", amounts=(3, 7, 11, 15)),
            _RowRule(
                "total",
                "Net amounts of derivatives",
                amounts=(3, 7, 11, 15),
                currency=(2, 6, 10, 14),
            ),
            _RowRule("section", "Reported as"),
            _RowRule(
                "detail",
                "Short-term investments",
                amounts=(3, 11),
                plain=(7, 15),
                currency=(2, 6, 10, 14),
            ),
            _RowRule("detail", "Other current assets", amounts=(3, 11), plain=(7, 15)),
            _RowRule(
                "detail", "Other long-term assets", amounts=(3, 11), plain=(7, 15)
            ),
            _RowRule(
                "detail", "Other current liabilities", amounts=(7, 15), plain=(3, 11)
            ),
            _RowRule(
                "detail", "Other long-term liabilities", amounts=(7, 15), plain=(3, 11)
            ),
            _RowRule("total", "Total", amounts=(3, 7, 11, 15), currency=(2, 6, 10, 14)),
        ),
    }
)


class _Refusal(Exception):
    def __init__(self, reason: AccountingRefusalReason, detail: str) -> None:
        self.reason = reason
        self.detail = detail


def _require(condition: bool, reason: AccountingRefusalReason, detail: str) -> None:
    if not condition:
        raise _Refusal(reason, detail)


def _text(node: etree._Element) -> str:
    return " ".join(" ".join(node.itertext()).split())


def _hash(node: etree._Element) -> str:
    return hashlib.sha256(etree.tostring(node, method="c14n")).hexdigest()


def _locator(node: etree._Element) -> FiscalDisclosureLocatorV1:
    return FiscalDisclosureLocatorV1(
        source_id=node.get("id"),
        xpath=node.getroottree().getpath(node),
        source_line=node.sourceline or 1,
        sha256=_hash(node),
        text=_text(node)[:4096],
    )


def _namespace(node: etree._Element, value: str) -> str | None:
    return (
        node.nsmap.get(value.split(":", 1)[0]) if ":" in value else node.nsmap.get(None)
    )


class _PresentationUse(StrEnum):
    DOCUMENT = auto()
    BODY = auto()
    BLOCK = auto()
    TABLE = auto()
    ROW = auto()
    FIRST_CELL = auto()
    CELL = auto()
    LABEL_PARAGRAPH = auto()
    COLUMN_PARAGRAPH = auto()
    HEADING = auto()
    INLINE = auto()
    SECTION_CONTENT = auto()
    NUMERIC_OCCURRENCE = auto()
    BREAK = auto()
    FOOTNOTE_LIST = auto()
    FOOTNOTE_MARKER = auto()
    FOOTNOTE_BODY = auto()
    FOOTNOTE_TEXT = auto()


_ELEMENT_USES = MappingProxyType(
    {
        f"{{{_XHTML}}}html": _PresentationUse.DOCUMENT,
        f"{{{_XHTML}}}body": _PresentationUse.BODY,
        f"{{{_XHTML}}}table": _PresentationUse.TABLE,
        f"{{{_XHTML}}}tr": _PresentationUse.ROW,
        f"{{{_XHTML}}}br": _PresentationUse.BREAK,
        f"{{{_IX}}}nonFraction": _PresentationUse.NUMERIC_OCCURRENCE,
        **{
            f"{{{_IX}}}{tag}": _PresentationUse.SECTION_CONTENT
            for tag in ("nonNumeric", "continuation", "footnote")
        },
    }
)

_STYLES_BY_USE = (
    (_PresentationUse.DOCUMENT, ("",)),
    (_PresentationUse.BODY, ("line-height:1;margin:auto;padding:8px",)),
    (
        _PresentationUse.BLOCK,
        (
            "",
            "font-family:arial;font-size:10pt",
        ),
    ),
    (
        _PresentationUse.TABLE,
        (
            "border-collapse:separate;border-spacing:0;margin-left:auto;margin-right:auto;table-layout:fixed;width:100.0%",
        ),
    ),
    (
        _PresentationUse.ROW,
        (
            "",
            "background-color:#e5e5e5;height:10pt;white-space:pre-wrap;word-break:break-word",
            "background-color:#ffffff;font-weight:bold;visibility:collapse",
            "background-color:#ffffff;height:10pt;white-space:pre-wrap;word-break:break-word",
            "height:10pt;white-space:pre-wrap;word-break:break-word",
            "height:2pt;white-space:pre-wrap;word-break:break-word",
            "height:4pt;white-space:pre-wrap;word-break:break-word",
            "height:7pt;white-space:pre-wrap;word-break:break-word",
            "visibility:collapse",
            "white-space:pre-wrap;word-break:break-word",
        ),
    ),
    (
        _PresentationUse.FIRST_CELL,
        (
            "",
            "border-bottom:0.5pt solid;vertical-align:bottom",
            "border-bottom:0.5pt solid;vertical-align:top",
            "border-top:0.5pt solid;vertical-align:top",
            "text-indent:12.25pt;vertical-align:bottom",
            "text-indent:12.25pt;vertical-align:top",
            "text-indent:24.5pt;vertical-align:top",
            "text-indent:36pt;vertical-align:top",
            "text-indent:48.25pt;vertical-align:top",
            "text-indent:60.5pt;vertical-align:top",
            "vertical-align:bottom",
            "vertical-align:middle",
            "vertical-align:top",
        ),
    ),
    (
        _PresentationUse.CELL,
        (
            "",
            "border-bottom:0.5pt solid #ffffff03;vertical-align:bottom",
            "border-bottom:0.5pt solid #ffffff03;vertical-align:top",
            "border-bottom:0.5pt solid;text-align:center;vertical-align:bottom",
            "border-bottom:0.5pt solid;vertical-align:bottom",
            "border-bottom:0.5pt solid;vertical-align:top",
            "border-bottom:1.5pt solid #ffffff03;vertical-align:bottom",
            "border-bottom:1.5pt solid #ffffff03;vertical-align:top",
            "border-bottom:1.5pt solid;text-align:center;vertical-align:bottom",
            "border-bottom:1.5pt solid;vertical-align:bottom",
            "border-top:0.5pt solid #ffffff03;vertical-align:bottom",
            "border-top:0.5pt solid #ffffff03;vertical-align:top",
            "border-top:0.5pt solid;text-align:center;vertical-align:bottom",
            "border-top:0.5pt solid;text-align:left;vertical-align:bottom",
            "border-top:0.5pt solid;vertical-align:bottom",
            "border-top:0.5pt solid;vertical-align:top",
            "border-top:1.5pt solid #ffffff03;vertical-align:bottom",
            "border-top:1.5pt solid #ffffff03;vertical-align:top",
            "border-top:1.5pt solid;text-align:center;vertical-align:bottom",
            "border-top:1.5pt solid;vertical-align:bottom",
            "text-align:center;vertical-align:bottom",
            "text-align:center;vertical-align:top",
            "text-align:left;vertical-align:bottom",
            "vertical-align:bottom",
            "vertical-align:middle",
            "vertical-align:top",
        ),
    ),
    (
        _PresentationUse.LABEL_PARAGRAPH,
        (
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-left:12.25pt;margin-top:0;padding-left:12.25pt;text-align:left;text-indent:-12.25pt",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-left:23.75pt;margin-top:0;padding-left:12.25pt;text-align:left;text-indent:-12.25pt",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-left:36pt;margin-top:0;padding-left:12.25pt;text-align:left;text-indent:-12.25pt",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-left:48.25pt;margin-top:0;padding-left:12.25pt;text-align:left;text-indent:-12.25pt",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:0;padding-left:12.25pt;text-align:left;text-indent:-12.25pt",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:0;text-align:left",
            "font-family:times new roman;font-size:2pt;margin-bottom:0;margin-top:0;text-align:left",
            "font-family:times new roman;font-size:4pt;margin-bottom:0;margin-top:0;text-align:left",
            "font-family:times new roman;font-size:7.5pt;margin-bottom:0;margin-top:0;padding-left:12.25pt;text-align:left;text-indent:-12.25pt",
            "font-family:times new roman;font-size:7.5pt;margin-bottom:0;margin-top:0;text-align:left",
            "font-family:times new roman;font-size:9pt;margin-bottom:0;margin-top:0;text-align:left",
        ),
    ),
    (
        _PresentationUse.COLUMN_PARAGRAPH,
        (
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:0;text-align:center",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:0;text-align:left",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:0;text-align:right",
            "font-family:times new roman;font-size:2pt;margin-bottom:0;margin-top:0;text-align:center",
            "font-family:times new roman;font-size:2pt;margin-bottom:0;margin-top:0;text-align:left",
            "font-family:times new roman;font-size:2pt;margin-bottom:0;margin-top:0;text-align:right",
            "font-family:times new roman;font-size:4pt;margin-bottom:0;margin-top:0;text-align:left",
            "font-family:times new roman;font-size:4pt;margin-bottom:0;margin-top:0;text-align:right",
            "font-family:times new roman;font-size:7.5pt;margin-bottom:0;margin-top:0;text-align:center",
            "font-family:times new roman;font-size:7.5pt;margin-bottom:0;margin-top:0;text-align:left",
            "font-family:times new roman;font-size:7.5pt;margin-bottom:0;margin-top:0;text-align:right",
        ),
    ),
    (
        _PresentationUse.HEADING,
        (
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:0;text-align:center",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:13.5pt;text-align:justify",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:4.5pt;text-align:center",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:4.5pt;text-align:justify",
            "font-family:times new roman;font-size:10pt;margin-bottom:0;margin-top:9pt;text-align:justify",
        ),
    ),
    (
        _PresentationUse.INLINE,
        (
            "",
            "-sec-ix-hidden:<id>",
            "color:#000000;font-family:arial;font-size:10pt;font-weight:bold;min-width:fit-content;white-space:pre-wrap",
            "color:#000000;font-family:arial;font-size:10pt;min-width:fit-content;text-decoration:underline;white-space:pre-wrap",
            "color:#000000;font-family:arial;font-size:10pt;min-width:fit-content;white-space:pre-wrap",
            "color:#000000;font-family:arial;font-size:6.7pt;min-width:fit-content;position:relative;top:-4.6899999999999995pt;white-space:pre-wrap",
            "color:#000000;font-family:arial;font-weight:bold;min-width:fit-content;white-space:pre-wrap",
            "color:#000000;font-family:arial;min-width:fit-content;white-space:pre-wrap",
            "color:#000000;min-width:fit-content;white-space:pre-wrap",
            "display:inline",
            "font-family:arial",
            "font-family:arial;min-width:fit-content;white-space:pre-wrap",
        ),
    ),
    (_PresentationUse.SECTION_CONTENT, ("",)),
    (_PresentationUse.NUMERIC_OCCURRENCE, ("", "display:inline")),
    (_PresentationUse.BREAK, ("",)),
    (
        _PresentationUse.FOOTNOTE_LIST,
        (
            "align-items:baseline;display:flex;justify-content:flex-start;margin-bottom:0;margin-top:0;min-width:4.537%;text-align:justify",
        ),
    ),
    (
        _PresentationUse.FOOTNOTE_MARKER,
        (
            "color:#000000;display:inline-flex;font-family:arial;font-size:10pt;justify-content:flex-start;min-width:4.537%;white-space:pre-wrap;word-break:keep-all",
        ),
    ),
    (_PresentationUse.FOOTNOTE_BODY, ("display:inline;width:100%",)),
    (
        _PresentationUse.FOOTNOTE_TEXT,
        (
            "color:#000000;font-family:arial;font-size:10pt;font-style:italic;min-width:fit-content;white-space:pre-wrap",
        ),
    ),
)

_COLUMN_WIDTHS = (
    ("balance_sheet", tuple("70% 1% 1% 12% 1% 1% 1% 12% 1%".split())),
    (
        "investments",
        tuple(
            "18.004% 1% 7.001% 1% 1% 7.001% 1% 1% 1% 8.002% 1% 1% 1% 7.101% 1% 1% 1% 6.701% 1.44% 1.2% 1% 7.762% 1.2% 1% 1% 7.702% 1.02% 1% 1% 7.862% 1%".split()
        ),
    ),
    (
        "investments",
        tuple(
            "17.996% 1.2% 6.679% 1% 1% 6.999% 1.3% 1% 1% 7.439% 1% 1% 1% 7.119% 1% 1.18% 1% 6.999% 1.26% 1% 1% 7.998% 1.32% 1% 1% 7.958% 1% 1% 1% 7.558% 1%".split()
        ),
    ),
    (
        "derivatives",
        tuple(
            "51.95% 1% 1.08% 8.922% 1% 1% 1.08% 8.922% 1% 1% 1.08% 8.922% 1% 1% 1.08% 8.962% 1%".split()
        ),
    ),
)


@dataclass(frozen=True)
class _PresentationGrammar:
    styles_by_use: tuple[tuple[_PresentationUse, tuple[str, ...]], ...]
    column_widths: tuple[tuple[str, tuple[str, ...]], ...]
    element_uses: tuple[tuple[str, _PresentationUse], ...]
    geometry_cell_style: str = "box-sizing:content-box;width:"
    xml_whitespace: str = " \t\r\n"
    html_css_whitespace: str = " \t\r\n\f"
    scale_pattern: str = r"[+-]?[0-9]+"
    column_span_pattern: str = r"\+?[0-9]+"
    relationship_item_type: Literal["xs:NCName"] = "xs:NCName"
    structural_table_ancestors: tuple[str, ...] = tuple(
        f"{{{_XHTML}}}{k}" for k in ("html", "body", "div")
    ) + tuple(f"{{{_IX}}}{k}" for k in ("nonNumeric", "continuation"))
    elements: tuple[str, ...] = tuple(
        f"{{{_XHTML}}}{tag}"
        for tag in ("html", "body", "div", "p", "span", "br", "table", "tr", "td", "th")
    ) + tuple(
        f"{{{_IX}}}{tag}"
        for tag in ("nonNumeric", "continuation", "nonFraction", "footnote")
    )
    attributes: tuple[str, ...] = (
        "style",
        "id",
        "class",
        "colspan",
        "rowspan",
        "decimals",
        "scale",
        "sign",
        "format",
        "unitRef",
        "contextRef",
        "name",
        "escape",
        "continuedAt",
        "{http://www.w3.org/XML/1998/namespace}lang",
    )
    nil_attribute: str = "{http://www.w3.org/2001/XMLSchema-instance}nil"
    non_nil_lexicals: tuple[str, ...] = ("false", "0")
    nil_whitespace: Literal["collapse"] = "collapse"
    ignored_namespaced_attributes: tuple[str, ...] = ("nil",)
    empty_geometry_element: str = f"{{{_XHTML}}}tr"
    empty_geometry_visibility: str = "collapse"
    class_element: str = f"{{{_XHTML}}}div"
    class_name: str = "item-list-element-wrapper"
    annotation_element: str = f"{{{_XHTML}}}span"
    annotation_property: str = "-sec-ix-hidden"
    annotation_reference_pattern: str = r"F_[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
    document_presentation_sources: tuple[str, ...] = tuple(
        f"{{{namespace}}}{name}"
        for namespace, names in (
            (_XHTML, ("style", "link", "script")),
            (_SVG, ("style", "script")),
        )
        for name in names
    )
    unprefixed_html_presentation_names: tuple[str, ...] = ("style", "link", "script")
    marker_element: str = f"{{{_XHTML}}}span"
    marker_text: str = "(a)"
    marker_displacement: tuple[tuple[str, str], ...] = (
        ("position", "relative"),
        ("top", "-4.6899999999999995pt"),
    )


_PRESENTATION_GRAMMAR = _PresentationGrammar(
    _STYLES_BY_USE, _COLUMN_WIDTHS, tuple(_ELEMENT_USES.items())
)
_PERMITTED_STYLES = MappingProxyType(
    {use: frozenset(styles) for use, styles in _PRESENTATION_GRAMMAR.styles_by_use}
)
_CSS_WS = _PRESENTATION_GRAMMAR.html_css_whitespace
_XML_WS = _PRESENTATION_GRAMMAR.xml_whitespace
_CSS_SPACE = re.compile("[" + _CSS_WS + "]+")
_XML_SPACE = re.compile("[" + _XML_WS + "]+")
_CSS_IMPORTANT = re.compile(r"![ \t\r\n\f]*important$", re.IGNORECASE | re.ASCII)


def _presentation_use(node: etree._Element) -> _PresentationUse:
    parent = node.getparent()
    if node.tag == f"{{{_XHTML}}}div":
        if node.get("class") == _PRESENTATION_GRAMMAR.class_name:
            _require(
                len(node) == 2
                and node[0].tag == f"{{{_XHTML}}}span"
                and node[1].tag == f"{{{_XHTML}}}div"
                and len(node[1]) == 1
                and node[1][0].tag == f"{{{_IX}}}footnote"
                and not len(node[0]),
                "unsupported_presentation",
                "The footnote list layout requires its marker and a single note body",
            )
            return _PresentationUse.FOOTNOTE_LIST
        if (
            parent is not None
            and parent.get("class") == _PRESENTATION_GRAMMAR.class_name
        ):
            return _PresentationUse.FOOTNOTE_BODY
        return _PresentationUse.BLOCK
    if node.tag == f"{{{_XHTML}}}span":
        if (
            parent is not None
            and parent.get("class") == _PRESENTATION_GRAMMAR.class_name
        ):
            return _PresentationUse.FOOTNOTE_MARKER
        if parent is not None and parent.tag == f"{{{_IX}}}footnote":
            return _PresentationUse.FOOTNOTE_TEXT
        return _PresentationUse.INLINE
    if node.tag in {f"{{{_XHTML}}}td", f"{{{_XHTML}}}th", f"{{{_XHTML}}}p"}:
        cell = parent if node.tag == f"{{{_XHTML}}}p" else node
        if cell is None or cell.tag not in {f"{{{_XHTML}}}td", f"{{{_XHTML}}}th"}:
            return _PresentationUse.HEADING
        first = cell.getprevious() is None
        if cell is node:
            return _PresentationUse.FIRST_CELL if first else _PresentationUse.CELL
        return (
            _PresentationUse.LABEL_PARAGRAPH
            if first
            else _PresentationUse.COLUMN_PARAGRAPH
        )
    return _ELEMENT_USES[node.tag]


def _css(node: etree._Element) -> dict[str, str]:
    raw = node.get("style", "")
    _require(
        raw.isascii(),
        "unsupported_presentation",
        "Disclosure styles require ASCII tokens",
    )
    declarations: dict[str, str] = {}
    for part in raw.split(";"):
        if not part.strip(_CSS_WS):
            continue
        name, sep, value = part.partition(":")
        name = name.strip(_CSS_WS).lower()
        _require(
            bool(sep) and name not in declarations,
            "unsupported_presentation",
            "An original style declaration is incomplete or repeated",
        )
        token = _CSS_SPACE.sub(" ", value.strip(_CSS_WS))
        value_token = _CSS_IMPORTANT.sub("", token).strip(_CSS_WS)
        normalized = _CSS_SPACE.sub(" ", value_token.strip(_CSS_WS)).lower()
        if name == _PRESENTATION_GRAMMAR.annotation_property:
            _require(
                node.tag == _PRESENTATION_GRAMMAR.annotation_element
                and re.fullmatch(
                    _PRESENTATION_GRAMMAR.annotation_reference_pattern, value_token
                )
                is not None,
                "unsupported_presentation",
                "The original SEC caption annotation requires an identifier",
            )
            normalized = "<id>"
        declarations[name] = normalized
    if declarations.get("visibility") == "visible":
        del declarations["visibility"]
    return declarations


def _style_recipe(declarations: dict[str, str]) -> str:
    return ";".join(f"{key}:{value}" for key, value in sorted(declarations.items()))


@dataclass(frozen=True)
class _VisibleDisclosure:
    text: str


@dataclass(frozen=True)
class _PresentNumericDisclosure:
    text: str


@dataclass(frozen=True)
class _EmptyCollapsedGeometry:
    pass


_DisclosureObservation = (
    _VisibleDisclosure | _PresentNumericDisclosure | _EmptyCollapsedGeometry
)


class _OriginalDisclosureReader:
    def __init__(self, check_deadline: Callable[[], float]) -> None:
        self._check_deadline = check_deadline
        self._observed: dict[etree._Element, _DisclosureObservation] = {}
        self._geometry_cells: set[etree._Element] = set()
        self._subtrees: set[etree._Element] = set()

    def read_table(self, table: etree._Element, role: DisclosureRole) -> None:
        _require(
            all(
                a.tag in _PRESENTATION_GRAMMAR.structural_table_ancestors
                for a in table.iterancestors()
            ),
            "unsupported_presentation",
            "The disclosure table requires block or original section ancestors",
        )
        geometry = table[0]
        _require(
            _css(geometry).get("visibility")
            == _PRESENTATION_GRAMMAR.empty_geometry_visibility,
            "contradictory_disclosure",
            "The first row must establish the disclosed column geometry",
        )
        widths = tuple(_css(cell).get("width", "") for cell in geometry)
        _require(
            (role, widths) in _PRESENTATION_GRAMMAR.column_widths
            and all(
                cell.tag == f"{{{_XHTML}}}td"
                and not len(cell)
                and _style_recipe(_css(cell))
                == _PRESENTATION_GRAMMAR.geometry_cell_style + width
                for cell, width in zip(geometry, widths, strict=True)
            ),
            "unsupported_presentation",
            "The geometry row must establish the original ordered column widths",
        )
        _require(
            all(cell.end == cell.start + 1 for cell in _cells(geometry)),
            "contradictory_disclosure",
            "Each original column needs a separate sizing cell",
        )
        self._geometry_cells.update(geometry)
        self.read(table)

    def _element(self, node: etree._Element) -> _DisclosureObservation:
        if node in self._observed:
            return self._observed[node]
        if len(self._observed) % 128 == 0:
            self._check_deadline()
        _require(
            node.tag in _PRESENTATION_GRAMMAR.elements
            and all(
                key in _PRESENTATION_GRAMMAR.attributes
                or (
                    key.startswith("{")
                    and key.rsplit("}", 1)[-1]
                    in _PRESENTATION_GRAMMAR.ignored_namespaced_attributes
                )
                for key in node.attrib
            ),
            "unsupported_presentation",
            "Original disclosure has unsupported presentation attributes or elements",
        )
        styles = _css(node)
        use = _presentation_use(node)
        if node not in self._geometry_cells:
            _require(
                _style_recipe(styles) in _PERMITTED_STYLES[use],
                "unsupported_presentation",
                f"Unsupported combination of declarations for {use.value}",
            )
        if use is _PresentationUse.BREAK:
            _require(
                not len(node) and not node.text,
                "unsupported_presentation",
                "A disclosed XHTML line break must be empty",
            )
        text = _text(node)
        _require(
            node.get("class") is None
            or (
                node.tag == _PRESENTATION_GRAMMAR.class_element
                and node.get("class") == _PRESENTATION_GRAMMAR.class_name
            ),
            "unsupported_presentation",
            "Original disclosure class is unsupported without a stylesheet",
        )
        _require(
            not (dict(_PRESENTATION_GRAMMAR.marker_displacement).keys() & styles.keys())
            or (
                node.tag == _PRESENTATION_GRAMMAR.marker_element
                and text == _PRESENTATION_GRAMMAR.marker_text
                and all(
                    styles.get(key) == value
                    for key, value in _PRESENTATION_GRAMMAR.marker_displacement
                )
            ),
            "unsupported_presentation",
            "Only the original bounded superscript marker displacement is supported",
        )
        observation: _DisclosureObservation
        if styles.get("visibility") == _PRESENTATION_GRAMMAR.empty_geometry_visibility:
            _require(
                node.tag == _PRESENTATION_GRAMMAR.empty_geometry_element
                and not text
                and not _inline(node)
                and not (node.tail or "").strip(_XML_WS),
                "unsupported_presentation",
                "Collapsed geometry cannot contain disclosure text, inline evidence or tail payload",
            )
            observation = _EmptyCollapsedGeometry()
        elif node.tag == f"{{{_IX}}}nonFraction":
            raw_nil = node.get(_PRESENTATION_GRAMMAR.nil_attribute)
            nil = None if raw_nil is None else raw_nil.strip(_XML_WS)
            _require(
                (nil is None or nil in _PRESENTATION_GRAMMAR.non_nil_lexicals)
                and bool(text),
                "unsupported_numeric",
                "Original numeric occurrence is nil, has invalid nil lexical form or has no value",
            )
            observation = _PresentNumericDisclosure(text)
        else:
            observation = _VisibleDisclosure(text)
        self._observed[node] = observation
        return observation

    def read(self, node: etree._Element) -> _DisclosureObservation:
        self._check_deadline()
        collapsed = False
        for ancestor in node.iterancestors():
            collapsed |= isinstance(self._element(ancestor), _EmptyCollapsedGeometry)
        if node not in self._subtrees:
            for child in node.iter():
                self._element(child)
            self._subtrees.update(node.iter())
        if collapsed:
            _require(
                not _text(node)
                and not _inline(node)
                and not (node.tail or "").strip(_XML_WS),
                "unsupported_presentation",
                "Collapsed geometry cannot support descendant disclosure evidence",
            )
            return _EmptyCollapsedGeometry()
        return self._element(node)

    def text(self, node: etree._Element) -> str:
        observation = self.read(node)
        return (
            "" if isinstance(observation, _EmptyCollapsedGeometry) else observation.text
        )

    def numeric_text(self, node: etree._Element) -> str:
        observation = self.read(node)
        _require(
            isinstance(observation, _PresentNumericDisclosure),
            "unsupported_numeric",
            "A present original numeric occurrence is required",
        )
        assert isinstance(observation, _PresentNumericDisclosure)
        return observation.text


@dataclass(frozen=True)
class _Cell:
    node: etree._Element
    start: int
    end: int


def _cells(row: etree._Element) -> tuple[_Cell, ...]:
    cells = []
    column = 0
    for node in row:
        _require(
            node.tag in {f"{{{_XHTML}}}td", f"{{{_XHTML}}}th"},
            "contradictory_disclosure",
            "Unexpected table cell namespace or element",
        )
        lexical = node.get("colspan", "1").strip(
            _PRESENTATION_GRAMMAR.html_css_whitespace
        )
        _require(
            re.fullmatch(_PRESENTATION_GRAMMAR.column_span_pattern, lexical)
            is not None,
            "contradictory_disclosure",
            "Invalid disclosed column span",
        )
        digits = lexical.removeprefix("+").lstrip("0") or "0"
        if len(digits) > len(str(_POLICY.max_cells)) or int(digits) > _POLICY.max_cells:
            raise SnapshotError(
                "FISCAL_ACCOUNTING_BUDGET_EXCEEDED",
                "Disclosure column span exceeds its limit",
            )
        span = int(digits)
        _require(
            span >= 1 and node.get("rowspan", "1") == "1",
            "contradictory_disclosure",
            "Unsupported disclosed row or column span",
        )
        cells.append(_Cell(node, column, column + span))
        column += span
    if column > _POLICY.max_cells:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_BUDGET_EXCEEDED", "Disclosure column bound exceeded"
        )
    return tuple(cells)


@dataclass(frozen=True)
class _Table:
    node: etree._Element
    heading: etree._Element
    rows: tuple[etree._Element, ...]
    header: tuple[_Cell, ...]
    dates: tuple[_Cell, ...]
    region: etree._Element
    candidates: tuple[etree._Element, ...]
    observed_dates: tuple[_Cell, ...]
    reader: _OriginalDisclosureReader


@dataclass(frozen=True)
class _Document:
    root: etree._Element
    tables: tuple[etree._Element, ...]
    ids: dict[str, etree._Element]
    headings: dict[etree._Element, etree._Element]
    paragraphs: tuple[etree._Element, ...]
    positions: dict[etree._Element, int]
    reader: _OriginalDisclosureReader


def _document(member: bytes, check_deadline: Callable[[], float]) -> _Document:
    check_deadline()
    if len(member) > _POLICY.max_primary_bytes:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_BUDGET_EXCEEDED", "Primary document byte bound exceeded"
        )
    try:
        root = etree.fromstring(
            member,
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                recover=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError as error:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_DOCUMENT_INVALID", "Original XML cannot be parsed safely"
        ) from error
    if root.getroottree().docinfo.doctype:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_DOCUMENT_INVALID", "DTD declarations are unsupported"
        )
    _require(
        not root.getroottree().xpath('/processing-instruction("xml-stylesheet")'),
        "unsupported_presentation",
        "External document presentation instructions are unsupported",
    )
    ids: dict[str, etree._Element] = {}
    tables = []
    headings = {}
    paragraphs = []
    positions = {}
    heading = None
    for index, node in enumerate(root.iter()):
        if index % 128 == 0:
            check_deadline()
        if index >= _POLICY.max_nodes:
            raise SnapshotError(
                "FISCAL_ACCOUNTING_BUDGET_EXCEEDED", "Original XML node bound exceeded"
            )
        positions[node] = index
        _require(
            node.tag not in _PRESENTATION_GRAMMAR.document_presentation_sources
            and not (
                isinstance(node.tag, str)
                and node.prefix is None
                and re.fullmatch(
                    "|".join(_PRESENTATION_GRAMMAR.unprefixed_html_presentation_names),
                    etree.QName(node).localname,
                    re.IGNORECASE | re.ASCII,
                )
                is not None
            ),
            "unsupported_presentation",
            "Stylesheets and scripted presentation are outside this original reader",
        )
        identity = node.get("id")
        if identity:
            _require(
                identity not in ids,
                "ambiguous_disclosure",
                "Original contains duplicate evidence identities",
            )
            ids[identity] = node
        if node.tag == f"{{{_XHTML}}}p":
            paragraphs.append(node)
            label = _text(node)
            if label.startswith("NOTE ") or label in {
                "BALANCE SHEETS",
                "CASH FLOWS STATEMENTS",
                "INCOME STATEMENTS",
                "COMPREHENSIVE INCOME STATEMENTS",
            }:
                heading = node
        if node.tag == f"{{{_XHTML}}}table":
            tables.append(node)
            if heading is not None:
                headings[node] = heading
    if len(tables) > _POLICY.max_tables:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_BUDGET_EXCEEDED", "Original table bound exceeded"
        )
    check_deadline()
    return _Document(
        root,
        tuple(tables),
        ids,
        headings,
        tuple(paragraphs),
        positions,
        _OriginalDisclosureReader(check_deadline),
    )


def _select_table(
    document: _Document, specification: _Disclosure, check_deadline: Callable[[], float]
) -> _Table:
    candidates = []
    observed_dates: list[_Cell] = []
    selected = []
    boundary = (
        specification.required_title or specification.heading,
        specification.end_heading,
    )
    starts, ends = (
        tuple(p for p in document.paragraphs if _text(p) == label) for label in boundary
    )
    _require(
        len(starts) == len(ends) == 1,
        "missing_disclosure",
        "Original disclosure section boundaries are missing or ambiguous",
    )
    for boundary_node in (*starts, *ends):
        document.reader.read(boundary_node)
    region_tables = tuple(
        node
        for node in document.tables
        if document.positions[starts[0]]
        < document.positions[node]
        < document.positions[ends[0]]
    )
    for table in region_tables:
        check_deadline()
        heading = document.headings.get(table)
        _require(
            heading is not None and _text(heading) == specification.heading,
            "contradictory_disclosure",
            "Unexpected table in the bounded disclosure section",
        )
        assert heading is not None
        document.reader.read(heading)
        _require(
            all(n.tag == f"{{{_XHTML}}}tr" for n in table),
            "contradictory_disclosure",
            "Section table contains content outside its rows",
        )
        rows = tuple(table)
        if len(rows) > _POLICY.max_rows:
            raise SnapshotError(
                "FISCAL_ACCOUNTING_BUDGET_EXCEEDED", "Disclosure row bound exceeded"
            )
        header_rows = tuple(
            _cells(row)
            for row in rows
            if len(row) and _text(row[0]) == specification.units_label
        )
        _require(
            len(header_rows) == 1,
            "missing_disclosure",
            "Section table has no unique unit header",
        )
        document.reader.read_table(table, specification.role)
        _require(
            not (table.text or "").strip(_XML_WS)
            and all(not (n.tail or "").strip(_XML_WS) for n in table),
            "contradictory_disclosure",
            "Section table contains content outside its physical rows",
        )
        header = header_rows[0]
        _require(
            tuple(_text(cell.node) for cell in header[1:] if _text(cell.node))
            == specification.columns,
            "contradictory_disclosure",
            "Section table has unknown or competing columns",
        )
        layouts = tuple(_cells(row) for row in rows)
        dates = tuple(
            cell
            for cells in layouts
            for cell in cells
            if _text(cell.node) in {_POLICY.current_label, _POLICY.comparative_label}
        )
        candidates.append(table)
        observed_dates.extend(dates)
        current = tuple(
            cell for cell in dates if _text(cell.node) == _POLICY.current_label
        )
        if len(current) != 1:
            continue
        if specification.date_mode == "columns":
            _require(
                len(dates) == 2
                and tuple(_text(cell.node) for cell in dates)
                == (_POLICY.current_label, _POLICY.comparative_label),
                "contradictory_disclosure",
                "Current and comparative columns are missing, duplicated or reversed",
            )
            _require(
                dates[0].end - dates[0].start == dates[1].end - dates[1].start
                and dates[0].end < dates[1].start,
                "contradictory_disclosure",
                "Current and comparative date spans no longer describe parallel columns",
            )
            if specification.columns:
                _require(
                    all(
                        len(
                            tuple(
                                cell
                                for cell in header
                                if _text(cell.node)
                                in {"Derivative Assets", "Derivative Liabilities"}
                                and date_cell.start
                                <= cell.start
                                < cell.end
                                <= date_cell.end
                            )
                        )
                        == 2
                        for date_cell in dates
                    ),
                    "contradictory_disclosure",
                    "Each derivative date must span its asset and liability headings",
                )
        else:
            _require(
                len(dates) == 1 and current[0].start == 0,
                "contradictory_disclosure",
                "Investment table has competing date evidence",
            )
        region = next(
            (
                p
                for p in table.iterancestors()
                if p.tag in {f"{{{_IX}}}nonNumeric", f"{{{_IX}}}continuation"}
            ),
            table,
        )
        selected.append((table, heading, rows, header, dates, region))
    _require(
        len(selected) == 1,
        "ambiguous_disclosure" if len(selected) > 1 else "missing_disclosure",
        f"Expected one current-period {specification.role} disclosure",
    )
    _require(
        len(candidates) == (2 if specification.date_mode == "table" else 1),
        "ambiguous_disclosure",
        "Unexpected extra disclosure table",
    )
    table, heading, rows, header, dates, region = selected[0]
    return _Table(
        table,
        heading,
        rows,
        header,
        dates,
        region,
        tuple(candidates),
        tuple(observed_dates),
        document.reader,
    )


def _inline(node: etree._Element) -> tuple[etree._Element, ...]:
    return tuple(
        n
        for n in node.iter()
        if isinstance(n.tag, str) and n.tag.startswith("{" + _IX + "}")
    )


def _row_coverage(
    table: _Table,
    spec: _Disclosure,
    check_deadline: Callable[[], float],
    *,
    comparative: bool = False,
) -> tuple[str, ...]:
    disclosed_text = table.reader.text
    rules = _ROW_GRAMMAR[spec.role]
    kinds = []
    index = 0
    contents = {f"{{{_XHTML}}}{tag}" for tag in ("p", "span", "br", "td", "th")}
    contents.add(f"{{{_IX}}}nonFraction")
    for row in table.rows:
        check_deadline()
        cells = _cells(row)
        _require(
            all(node.tag in contents for node in row.iterdescendants())
            and all(
                not any(
                    inner.tag in {f"{{{_XHTML}}}td", f"{{{_XHTML}}}th"}
                    for inner in cell.node.iterdescendants()
                )
                for cell in cells
            )
            and not (row.text or "").strip(_XML_WS)
            and all(not (cell.node.tail or "").strip(_XML_WS) for cell in cells),
            "contradictory_disclosure",
            "Unexpected content outside the disclosure cells",
        )
        if not any(disclosed_text(cell.node) or _inline(cell.node) for cell in cells):
            kinds.append("spacer")
            continue
        _require(
            bool(cells) and index < len(rules),
            "incomplete_bridge",
            "Unclassified nonempty disclosure row",
        )
        rule = rules[index]
        caption = (
            _POLICY.comparative_label
            if comparative and rule.caption == _POLICY.current_label
            else rule.caption
        )
        _require(
            cells[0].start == 0
            and cells[0].end == 1
            and disclosed_text(cells[0].node) == caption
            and tuple(n.get("name") for n in _inline(cells[0].node))
            == rule.caption_facts,
            "incomplete_bridge",
            f"Unexpected {spec.role} row at {row.sourceline}, expected {caption!r}",
        )
        data = {cell.start: cell for cell in cells[1:]}
        expected = {pos: (end, text) for pos, end, text in rule.literals}
        for pos in rule.plain:
            expected[pos] = (pos + 1, "0")
        for pos in rule.currency:
            expected[pos] = (pos + 1, "$")
        for pos in rule.amounts:
            cell = data.get(pos)
            _require(
                cell is not None and cell.end == pos + 1,
                "contradictory_disclosure",
                "Disclosed monetary cell has an unexpected span",
            )
            assert cell is not None
            tags = _inline(cell.node)
            _require(
                len(tags) == 1,
                "ambiguous_disclosure" if len(tags) > 1 else "missing_disclosure",
                "Monetary cell requires one tagged amount",
            )
            node = tags[0]
            lexical = disclosed_text(node)
            display = disclosed_text(cell.node)
            _require(
                node.tag == f"{{{_IX}}}nonFraction"
                and re.fullmatch(
                    r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?", lexical
                )
                is not None
                and display in (lexical, "( " + lexical),
                "contradictory_disclosure",
                "Monetary cell must contain exactly one displayed amount",
            )
            if display.startswith("("):
                expected[pos + 1] = (pos + 2, ")")
        for pos, (end, text) in expected.items():
            cell = data.get(pos)
            _require(
                cell is not None
                and cell.end == end
                and disclosed_text(cell.node) == text
                and not _inline(cell.node),
                "contradictory_disclosure",
                "Unexpected money, span, or inline evidence in a disclosure cell",
            )
        _require(
            all(
                pos in rule.amounts
                or pos in expected
                or (not disclosed_text(cell.node) and not _inline(cell.node))
                for pos, cell in data.items()
            ),
            "contradictory_disclosure",
            "Unclassified disclosure cell carries content",
        )
        kinds.append(rule.kind)
        index += 1
    _require(
        index == len(rules), "incomplete_bridge", "Required disclosure rows are absent"
    )
    return tuple(kinds)


def _derivative_endpoints(
    document: _Document,
    table: _Table,
    spec: _Disclosure,
    report_facts: tuple[ParsedXbrlFactV1, ...],
    check_deadline: Callable[[], float],
) -> set[str]:
    disclosed_text = document.reader.text
    endpoints = set()
    dates = []
    for candidate in table.candidates:
        rows = tuple(candidate.iter(f"{{{_XHTML}}}tr"))
        dated = [
            disclosed_text(row[0])
            for row in rows
            if len(row)
            and disclosed_text(row[0])
            in {_POLICY.current_label, _POLICY.comparative_label}
        ]
        _require(
            len(dated) == 1,
            "contradictory_disclosure",
            "Investment table must have one date",
        )
        dates.extend(dated)
        if candidate is not table.node:
            _row_coverage(
                replace(table, node=candidate, rows=rows),
                spec,
                check_deadline,
                comparative=True,
            )
        focus_rows = [
            row
            for row in rows
            if len(row) and disclosed_text(row[0]) == "Derivatives, net (a)"
        ]
        _require(
            len(focus_rows) == 1,
            "contradictory_disclosure",
            "Expected a single footnoted investment row per date",
        )
        concepts = dict(_POLICY.endpoint_columns)
        for cell in _cells(focus_rows[0]):
            if cell.start in concepts:
                tags = _inline(cell.node)
                _require(
                    len(tags) == 1 and bool(tags[0].get("id")),
                    "contradictory_disclosure",
                    "Each dated derivative endpoint must identify one original fact",
                )
                node = tags[0]
                _require(
                    node.get("name") == "us-gaap:" + concepts[cell.start]
                    and _namespace(node, node.get("name", "")) == _GAAP,
                    "contradictory_disclosure",
                    "Linked derivative has a different concept from its disclosed column",
                )
                value, scale, decimals = _amount(node, document.reader)
                _require(
                    scale == 6
                    and decimals == "-6"
                    and (
                        (node.get("sign") == "-")
                        == disclosed_text(cell.node).startswith("(")
                    )
                    and node.get("sign") in (None, "-"),
                    "contradictory_disclosure",
                    "Linked derivative has inconsistent sign or precision",
                )
                _match_reported_money(
                    document,
                    node,
                    report_facts,
                    instant=_POLICY.instant
                    if dated[0] == _POLICY.current_label
                    else _POLICY.comparative_instant,
                    expected_dimensions=(
                        ("us-gaap:FinancialInstrumentAxis", "us-gaap:DerivativeMember"),
                    ),
                    value=value,
                    scale=scale,
                    decimals=decimals,
                    description="dated investment derivative",
                )
                endpoints.add(node.get("id", ""))
    _require(
        sorted(dates) == sorted((_POLICY.current_label, _POLICY.comparative_label)),
        "contradictory_disclosure",
        "Footnote must cover both investment dates",
    )
    return endpoints


def _one_id(document: _Document, identity: str, tag: str) -> etree._Element:
    node = document.ids.get(identity)
    if node is None or node.tag != tag:
        raise _Refusal(
            "fact_context_mismatch",
            "Original context or unit is absent or has another namespace",
        )
    return node


def _amount(
    node: etree._Element, reader: _OriginalDisclosureReader
) -> tuple[Decimal, int, str]:
    lexical = reader.numeric_text(node)
    if len(lexical) > _POLICY.max_numeric_digits:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_BUDGET_EXCEEDED",
            "Monetary lexical length exceeds its limit",
        )
    _require(
        re.fullmatch(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?", lexical)
        is not None,
        "unsupported_numeric",
        "Original monetary lexical value is unsupported or unbounded",
    )
    _require(
        node.get("format") == "ixt:num-dot-decimal"
        and _namespace(node, node.get("format", ""))
        == "http://www.xbrl.org/inlineXBRL/transformation/2022-02-16",
        "unsupported_numeric",
        "Original numeric transform is unsupported",
    )
    try:
        scale_text = node.get("scale", "0").strip(_XML_WS)
        decimals = node.get("decimals", "")
        if len(scale_text) > 5 or len(decimals) > 5:
            raise SnapshotError(
                "FISCAL_ACCOUNTING_BUDGET_EXCEEDED",
                "Original numeric exponent length exceeds its limit",
            )
        _require(
            re.fullmatch(_PRESENTATION_GRAMMAR.scale_pattern, scale_text) is not None,
            "unsupported_numeric",
            "The original scale requires an XML Schema integer",
        )
        scale = int(scale_text)
        if abs(scale) > _POLICY.max_scale or (
            re.fullmatch(r"-?[0-9]+", decimals)
            and abs(int(decimals)) > _POLICY.max_scale
        ):
            raise SnapshotError(
                "FISCAL_ACCOUNTING_BUDGET_EXCEEDED",
                "Original numeric exponent exceeds its limit",
            )
        _require(
            abs(scale) <= _POLICY.max_scale
            and (
                decimals == "INF"
                or (
                    re.fullmatch(r"-?[0-9]{1,4}", decimals) is not None
                    and abs(int(decimals)) <= _POLICY.max_scale
                )
            ),
            "unsupported_numeric",
            "Original precision or scale is unbounded",
        )
        _require(
            node.get("sign") in {None, "+", "-"},
            "unsupported_numeric",
            "Original numeric sign is unsupported",
        )
        with localcontext() as context:
            context.prec = 4400
            value = Decimal(lexical.replace(",", "")).scaleb(scale)
            if node.get("sign") == "-":
                value = -value
        _require(
            value.is_finite(), "unsupported_numeric", "Original amount is not finite"
        )
        return value, scale, decimals
    except (ValueError, InvalidOperation) as error:
        raise _Refusal(
            "unsupported_numeric", "Original precision or amount cannot be read"
        ) from error


def _reported_amount(raw: str) -> Decimal:
    if len(raw) > _POLICY.max_numeric_digits:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_BUDGET_EXCEEDED",
            "Report monetary lexical length exceeds its limit",
        )
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise _Refusal(
            "unsupported_numeric", "Retained report amount is invalid"
        ) from error
    _require(
        value.is_finite() and abs(value.adjusted()) <= 2 * _POLICY.max_scale,
        "unsupported_numeric",
        "Retained report amount is not finite or bounded",
    )
    return value


@dataclass(frozen=True)
class _LocatedAmount:
    row: etree._Element
    header: _Cell
    date: _Cell
    amount: _Cell
    closing: _Cell


def _locate_amount(
    table: _Table,
    role: _FactRole | _PlainZeroRole,
    disclosure: _Disclosure,
) -> _LocatedAmount:
    disclosed_text = table.reader.text
    rows = tuple(
        row for row in table.rows if len(row) and disclosed_text(row[0]) == role.row
    )
    _require(
        len(rows) == 1,
        "ambiguous_disclosure" if len(rows) > 1 else "missing_disclosure",
        f"Missing or competing row for {role.role}",
    )
    date = next(
        cell
        for cell in table.dates
        if disclosed_text(cell.node) == _POLICY.current_label
    )
    amount_column = disclosure.amount_column
    headers = tuple(
        cell
        for cell in (table.dates if not disclosure.columns else table.header)
        if disclosed_text(cell.node) == disclosure.selected_column
        and cell.start == amount_column - 1
        and cell.end == amount_column + 1
    )
    _require(
        len(headers) == 1
        and (disclosure.date_mode == "table" or date.start <= amount_column < date.end),
        "contradictory_disclosure",
        f"Unexpected current column for {role.role}",
    )
    cells = tuple(
        cell
        for cell in _cells(rows[0])
        if amount_column - 1 <= cell.start <= amount_column + 1
    )
    _require(
        len(cells) == 3 and all(cell.end == cell.start + 1 for cell in cells),
        "missing_disclosure",
        f"Incomplete amount position for {role.role}",
    )
    currency, amount, closing = cells
    _require(
        disclosed_text(currency.node) in {"", "$"}
        and not any(
            n.tag.startswith("{" + _IX + "}")
            for part in (currency, closing)
            for n in part.node.iter()
            if isinstance(n.tag, str)
        ),
        "contradictory_disclosure",
        f"Unsupported amount adornment for {role.role}",
    )
    return _LocatedAmount(rows[0], headers[0], date, amount, closing)


def _plain_zero(
    table: _Table, role: _PlainZeroRole, disclosure: _Disclosure
) -> FiscalAccountingPlainZeroV1:
    disclosed_text = table.reader.text
    located = _locate_amount(table, role, disclosure)
    _require(
        disclosed_text(located.amount.node) == "0"
        and not disclosed_text(located.closing.node)
        and not any(
            n.tag.startswith("{" + _IX + "}")
            for n in located.amount.node.iter()
            if isinstance(n.tag, str)
        ),
        "contradictory_disclosure",
        f"Expected a single untagged displayed zero for {role.row}",
    )
    return FiscalAccountingPlainZeroV1(
        role=role.role,
        row_sha256=_hash(located.row),
        heading=_locator(table.heading),
        region_sha256=_hash(table.region),
        row_label=_locator(located.row[0]),
        column_header=_locator(located.header.node),
        date_header=_locator(located.date.node),
        cell=_locator(located.amount.node),
        logical_column=located.amount.start,
        table_sha256=_hash(table.node),
    )


def _match_reported_money(
    document: _Document,
    node: etree._Element,
    report_facts: tuple[ParsedXbrlFactV1, ...],
    *,
    instant: date,
    expected_dimensions: tuple[tuple[str, str], ...],
    value: Decimal,
    scale: int,
    decimals: str,
    description: str,
) -> tuple[etree._Element, etree._Element, ParsedXbrlFactV1]:
    context = _one_id(document, node.get("contextRef", ""), f"{{{_XBRLI}}}context")
    identifiers = tuple(context.iter(f"{{{_XBRLI}}}identifier"))
    instants = tuple(context.iter(f"{{{_XBRLI}}}instant"))
    members = tuple(context.iter(f"{{{_XBRLDI}}}explicitMember"))
    _require(
        tuple(child.tag for child in context)
        == (f"{{{_XBRLI}}}entity", f"{{{_XBRLI}}}period")
        and tuple(child.tag for child in context[0])
        == (
            (f"{{{_XBRLI}}}identifier", f"{{{_XBRLI}}}segment")
            if expected_dimensions
            else (f"{{{_XBRLI}}}identifier",)
        )
        and (not expected_dimensions or tuple(context[0][1]) == members)
        and tuple(context[1]) == instants
        and len(identifiers) == 1
        and identifiers[0].get("scheme") == "http://www.sec.gov/CIK"
        and identifiers[0].text == _POLICY.issuer
        and len(instants) == 1
        and instants[0].text == instant.isoformat()
        and not tuple(context.iter(f"{{{_XBRLI}}}startDate"))
        and not tuple(context.iter(f"{{{_XBRLI}}}endDate"))
        and not tuple(context.iter(f"{{{_XBRLDI}}}typedMember")),
        "fact_context_mismatch",
        f"Entity or instant differs for {description}",
    )
    dimensions = tuple(sorted((m.get("dimension", ""), m.text or "") for m in members))
    dimension_namespaces = tuple(
        sorted(
            (
                m.get("dimension", ""),
                _namespace(m, m.get("dimension", "")),
                _namespace(m, m.text or ""),
            )
            for m in members
        )
    )
    _require(
        dimensions == expected_dimensions
        and all(
            axis_ns == member_ns == _GAAP
            for _, axis_ns, member_ns in dimension_namespaces
        ),
        "fact_context_mismatch",
        f"Dimensions do not describe the disclosed role {description}",
    )
    unit = _one_id(document, node.get("unitRef", ""), f"{{{_XBRLI}}}unit")
    measures = tuple(unit.iter(f"{{{_XBRLI}}}measure"))
    _require(
        tuple(unit) == measures
        and len(measures) == 1
        and measures[0].text == "iso4217:USD"
        and _namespace(measures[0], measures[0].text or "") == _ISO4217
        and not tuple(unit.iter(f"{{{_XBRLI}}}divide")),
        "fact_context_mismatch",
        f"Currency unit differs for {description}",
    )
    report_matches = tuple(
        dict.fromkeys(
            fact
            for fact in report_facts
            if fact.concept == node.get("name")
            and fact.context_id == context.get("id")
            and fact.namespace_uri == _GAAP
            and fact.unit == "iso4217:USD"
            and fact.entity_identifier == _POLICY.issuer
            and fact.entity_scheme == identifiers[0].get("scheme")
            and fact.instant == instant
            and fact.period_start is None
            and fact.period_end is None
            and fact.dimensions == dimensions
            and fact.dimension_namespace_uris == dimension_namespaces
            and fact.scale == scale
            and fact.decimals == decimals
            and fact.is_numeric
            and _reported_amount(fact.value) == value
        )
    )
    _require(
        len(report_matches) == 1,
        "fact_context_mismatch",
        f"Original cell does not match the retained report for {description}",
    )
    return context, unit, report_matches[0]


def _select_fact(
    document: _Document,
    table: _Table,
    role: _FactRole,
    disclosure: _Disclosure,
    report_facts: tuple[ParsedXbrlFactV1, ...],
) -> FiscalAccountingSemanticFactV1:
    disclosed_text = document.reader.text
    located = _locate_amount(table, role, disclosure)
    row, cell = located.row, located.amount
    matches = tuple(cell.node.iter(f"{{{_IX}}}nonFraction"))
    _require(
        len(matches) == 1,
        "ambiguous_disclosure" if len(matches) > 1 else "missing_disclosure",
        f"Expected one disclosed numeric cell for {role.role}",
    )
    node = matches[0]
    _require(
        node.get("name") == "us-gaap:" + role.concept
        and _namespace(node, node.get("name", "")) == _GAAP,
        "contradictory_disclosure",
        f"Concept does not describe {role.role}",
    )
    value, scale, decimals = _amount(node, document.reader)
    _require(
        scale == 6 and decimals == "-6",
        "unsupported_numeric",
        "The disclosed in-millions scale or precision changed",
    )
    negative_display = role.presentation in {"negative", "deduction"}
    expected_cell = role.displayed_amount(disclosed_text(node))
    _require(
        disclosed_text(cell.node) == expected_cell
        and disclosed_text(located.closing.node) == (")" if negative_display else "")
        and role.has_expected_sign(node.get("sign"), value),
        "contradictory_disclosure",
        f"Displayed amount or sign differs for {role.role}",
    )
    context, unit, report_fact = _match_reported_money(
        document,
        node,
        report_facts,
        instant=_POLICY.instant,
        expected_dimensions=role.tagged_dimensions,
        value=value,
        scale=scale,
        decimals=decimals,
        description=role.role,
    )
    identity = node.get("id", "")
    _require(
        bool(identity), "missing_disclosure", "Selected original fact has no identity"
    )
    review = FiscalReviewFactV1(
        fact_id=identity,
        fact=report_fact,
        table_index=document.tables.index(table.node),
        row_index=table.rows.index(row),
        table_sha256=_hash(table.node),
        row_sha256=_hash(row),
        raw_lexical=disclosed_text(node),
        raw_sign=node.get("sign"),
        raw_scale=scale,
        raw_decimals=decimals,
        value=value,
    )
    semantic = FiscalAccountingSemanticFactV1(
        role=role.role,
        transcription=review,
        original_fact=_locator(node),
        disclosure=role.disclosure,
        heading=_locator(table.heading),
        row_label=_locator(row[0]),
        column_header=_locator(located.header.node),
        date_header=_locator(located.date.node),
        cell=_locator(cell.node),
        context=_locator(context),
        unit=_locator(unit),
        logical_column=cell.start,
        region_sha256=_hash(table.region),
        presented_sign=role.presentation,
    )
    return semantic


@dataclass(frozen=True)
class _FootnoteRelationship:
    node: etree._Element
    sources: tuple[str, ...]
    destinations: tuple[str, ...]


def _reference_list(raw: str) -> tuple[str, ...]:
    tokens = tuple(_XML_SPACE.split(raw.strip(_XML_WS)))
    try:
        for token in tokens:
            etree.QName("urn:xbrl:reference", token)
    except ValueError as error:
        raise _Refusal(
            "contradictory_disclosure",
            "Footnote relationships require nonempty XML NCName lists",
        ) from error
    return tokens


def _focus_relationships(
    document: _Document, focus: str, check_deadline: Callable[[], float]
) -> list[_FootnoteRelationship]:
    relationships = []
    for node in document.root.iter(f"{{{_IX}}}relationship"):
        check_deadline()
        raw_from = node.get("fromRefs", "")
        raw_to = node.get("toRefs", "")
        if focus not in raw_from and focus not in raw_to:
            continue
        sources, destinations = _reference_list(raw_from), _reference_list(raw_to)
        if focus in sources or focus in destinations:
            relationships.append(_FootnoteRelationship(node, sources, destinations))
    return relationships


def _read_disclosures(
    source: FiscalClassificationSource,
    member: bytes,
    *,
    check_deadline: Callable[[], float],
) -> tuple[
    tuple[FiscalAccountingSemanticFactV1, ...],
    tuple[FiscalAccountingPlainZeroV1, ...],
    FocusFootnote,
    tuple[FiscalAccountingCounterevidenceScanV1, ...],
    tuple[FiscalSourceReconciliationV1, ...],
]:
    document = _document(member, check_deadline)
    tables = {
        specification.role: _select_table(document, specification, check_deadline)
        for specification in _POLICY.disclosures
    }
    outcome = source.evidence.outcome
    if not isinstance(outcome, FiscalValidationCompleteRefusedV1):
        raise _Refusal(
            "unsupported_source", "A complete raw-refused source is required"
        )
    disclosures = {spec.role: spec for spec in _POLICY.disclosures}
    coverage = {
        role: _row_coverage(table, disclosures[role], check_deadline)
        for role, table in tables.items()
    }
    facts = {}
    semantics = []
    for role in _POLICY.facts:
        check_deadline()
        semantic = _select_fact(
            document,
            tables[role.disclosure],
            role,
            disclosures[role.disclosure],
            outcome.claim.report.facts,
        )
        facts[role.role] = semantic.transcription
        semantics.append(semantic)
    _require(
        len({fact.fact_id for fact in facts.values()}) == len(_POLICY.facts),
        "ambiguous_disclosure",
        "Evidence is reused between distinct disclosed roles",
    )
    focus = source.witness.witness.actual_focus
    actual = facts["investment_derivative"]
    _require(
        focus.fact_id == actual.fact_id
        and focus.fact == actual.fact
        and Decimal(focus.numeric_value) == actual.value,
        "focus_mismatch",
        "Actual diagnostic focus is not the independently selected Note 4 short-term derivative",
    )
    _require(
        all(
            facts[left].value == facts[right].value
            for left, right in _POLICY.exact_pairs
        ),
        "contradictory_disclosure",
        "Signed cross-note derivative amount or both Note 5 totals disagree",
    )
    relationships = _focus_relationships(document, actual.fact_id, check_deadline)
    _require(
        len(relationships) == 1
        and relationships[0].node.get("linkRole") == _POLICY.link_role
        and relationships[0].node.get("arcrole") == _POLICY.arcrole,
        "contradictory_disclosure",
        "Unsupported or ambiguous focus fact-footnote relationships",
    )
    endpoints = relationships[0].sources
    declared = _derivative_endpoints(
        document,
        tables["investments"],
        disclosures["investments"],
        outcome.claim.report.facts,
        check_deadline,
    )
    _require(
        len(endpoints) == len(set(endpoints)) and set(endpoints) == declared,
        "contradictory_disclosure",
        "Footnote endpoints differ from the dated derivative rows",
    )
    targets = relationships[0].destinations
    _require(
        len(targets) == 1,
        "contradictory_disclosure",
        "Focus requires one footnote destination",
    )
    footnote = document.ids.get(targets[0])
    if footnote is None or footnote.tag != f"{{{_IX}}}footnote":
        raise _Refusal("missing_disclosure", "Missing focus footnote destination")
    _require(
        not footnote.get("continuedAt")
        and _text(footnote) == _POLICY.footnote_text
        and sum(
            _text(n) == _POLICY.footnote_text
            for n in document.root.iter(f"{{{_IX}}}footnote")
        )
        == 1,
        "contradictory_disclosure",
        "Focus must link to the unique Note 5 fair-values cross-reference",
    )
    footnote_parent = footnote.getparent()
    if footnote_parent is not None and footnote_parent.getparent() is not None:
        document.reader.read(footnote_parent.getparent())
    _require(
        footnote_parent is not None
        and footnote_parent.getparent() is not None
        and _text(footnote_parent.getparent()) == "(a) " + _POLICY.footnote_text,
        "contradictory_disclosure",
        "Cross-reference does not have the disclosed footnote (a) role",
    )
    mark_containers = []
    for note in document.root.iter(f"{{{_IX}}}footnote"):
        if (
            document.positions[tables["investments"].node]
            < document.positions[note]
            < document.positions[tables["derivatives"].heading]
        ):
            wrapper = note.getparent()
            container = wrapper.getparent() if wrapper is not None else None
            if container is not None and _text(container).startswith("(a) "):
                document.reader.read(container)
                mark_containers.append(container)
    _require(
        len(mark_containers) == 1 and mark_containers[0] is footnote_parent.getparent(),
        "contradictory_disclosure",
        "Investment note must have a single marked (a) footnote container",
    )
    _require(
        document.positions[tables["investments"].node]
        < document.positions[footnote]
        < document.positions[tables["derivatives"].heading],
        "contradictory_disclosure",
        "Note 4 focus must link uniquely to its Note 5 cross-reference in the investment note",
    )
    plain_zeros = []
    reconciliations = []
    for bridge in _POLICY.bridges:
        check_deadline()
        for location in bridge.plain_zeros:
            plain_zeros.append(
                _plain_zero(
                    tables[location.disclosure],
                    location,
                    disclosures[location.disclosure],
                )
            )
        item = _reconciliation(bridge, facts)
        _require(
            item.residual.copy_abs() <= item.precision_allowance,
            "reconciliation_mismatch",
            f"Disclosed bridge does not reconcile at source precision: {bridge.description}",
        )
        reconciliations.append(item)
    scans = tuple(
        FiscalAccountingCounterevidenceScanV1(
            disclosure=role,
            candidates=tuple(_locator(node) for node in table.candidates),
            row_kinds=coverage[role],
            selected_table_sha256=_hash(table.node),
            observed_date_headers=tuple(
                _locator(cell.node) for cell in table.observed_dates
            ),
            competing_columns=tuple(
                _locator(cell.node)
                for cell in table.header
                if _text(cell.node) and _text(cell.node) != "(In millions)"
            ),
            examined_numeric_cells=sum(
                1 for _ in table.node.iter(f"{{{_IX}}}nonFraction")
            ),
        )
        for role, table in tables.items()
    )
    assert footnote_parent is not None
    container = footnote_parent.getparent()
    assert container is not None
    link = FocusFootnote(
        focus_id=actual.fact_id,
        relationship=_locator(relationships[0].node),
        from_refs=endpoints,
        to_ref=targets[0],
        footnote=_locator(footnote),
        container=_locator(container),
        link_role=_POLICY.link_role,
        arcrole=_POLICY.arcrole,
    )
    check_deadline()
    return tuple(semantics), tuple(plain_zeros), link, scans, tuple(reconciliations)


def _load_resources() -> str:
    try:
        _document_dates()
        _assertion_dates()
        return fiscal_mapping_policy_digest()
    except (OSError, ValueError) as error:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_RESOURCE_UNAVAILABLE",
            "Required accounting policy resources are unavailable",
        ) from error


def _check_source(
    source: FiscalClassificationSource,
    archive_hash: str,
    source_digest: str,
    witness_digest: str,
) -> None:
    mapping_digest = _load_resources()
    evidence, scope = source.evidence, source.scope
    filing, outcome = evidence.request.filing, evidence.outcome
    _require(
        filing.cik == _POLICY.issuer
        and filing.accession_number == _POLICY.accession
        and filing.primary_document == _POLICY.primary
        and filing.report_period_end == _POLICY.instant
        and filing.form == "10-Q"
        and not filing.is_amendment,
        "unsupported_source",
        "Policy supports only the original Microsoft 2024-09-30 10-Q accession",
    )
    if not isinstance(outcome, FiscalValidationCompleteRefusedV1):
        raise _Refusal(
            "unsupported_source", "Policy requires complete raw-refused validation"
        )
    report = outcome.claim.report
    witness = source.witness.witness
    _require(
        scope.source_validation_ref.artifact_id == evidence.artifact_id
        and scope.source_validation_ref.content_hash == source_digest
        and scope.source_validation_ref.role == "fiscal-original-validation"
        and scope.source_validation_ref.media_type == "application/json"
        and scope.source_binding_digest == source_digest
        and scope.issuer_id == filing.cik
        and scope.accession_number == filing.accession_number
        and scope.cutoff_at == evidence.request.valuation_timestamp
        and scope.validation_kind == "complete_refused"
        and scope.runtime == outcome.runtime
        and scope.raw_report_digest == sha256_digest(report.model_dump(mode="json"))
        and scope.parser_action_refs == outcome.action_refs
        and scope.display_profile_digest == fiscal_display_profile_digest()
        and scope.mapping_policy_digest == mapping_digest
        and filing.accepted_at <= scope.cutoff_at
        and outcome.claim.source.available_at <= scope.cutoff_at
        and outcome.claim.metadata_status == "matched"
        and outcome.integrity.quality_decision == "block",
        "source_scope_mismatch",
        "Source-use scope differs from exact retained validation, cutoff, runtime or policies",
    )
    _require(
        scope.witness_ref is not None
        and scope.witness_ref.artifact_id == source.witness.artifact_id
        and scope.witness_ref.role == "fiscal-diagnostic-focus-witness-v1"
        and scope.witness_ref.media_type == "application/json"
        and scope.witness_ref.content_hash == witness_digest
        and witness.source_validation_ref == scope.source_validation_ref
        and witness.filing == filing
        and witness.cutoff == scope.cutoff_at
        and witness.request_digest == evidence.request.digest
        and witness.runtime == outcome.runtime
        and witness.integrity == outcome.integrity
        and witness.source_responses == outcome.responses
        and witness.source_available_at == outcome.claim.source.available_at
        and witness.raw_report_digest == scope.raw_report_digest
        and witness.raw_report_fact_digest == fact_semantic_digest(report)
        and witness.raw_report_findings_digest
        == sha256_digest(sorted(report.findings, key=sha256_digest))
        and tuple(
            sorted(
                (
                    ref
                    for action in witness.actions
                    for ref in (
                        action.result_ref,
                        action.report_ref,
                        action.delivery_ref,
                    )
                ),
                key=lambda ref: ref.artifact_id,
            )
        )
        == outcome.action_refs,
        "source_scope_mismatch",
        "Witness does not bind exact source, report, actions, runtime and cutoff",
    )
    findings = tuple(f for f in report.findings if f.code == _POLICY.diagnostic)
    _require(
        len(findings) == 1
        and report.blocking_finding_codes() == (_POLICY.diagnostic,)
        and not any(
            {finding.severity, finding.rule_severity} & {"critical", "fatal"}
            for finding in report.findings
        ),
        "unsupported_diagnostic",
        "Another, ambiguous or critical diagnostic blocks this source",
    )
    finding = findings[0]
    applicability = report.finding_applicability(finding)
    _require(
        finding == witness.raw_finding
        and finding.rule_severity == "error"
        and finding.severity == "warning"
        and applicability is not None
        and applicability.status == "active"
        and witness.filing_context == report.dqc_filing_context,
        "unsupported_diagnostic",
        "The exact original diagnostic is not active with unchanged error/warning severity",
    )
    _require(
        witness.applicability_policy_digest == witness.filing_context.policy_digest
        and witness.raw_report_fact_digest == outcome.integrity.normalized_fact_digest,
        "source_scope_mismatch",
        "Witness applicability or normalized facts differ from the source",
    )
    for action in witness.actions:
        result = ParserActionResultV2(
            request=action.request, report_content_hash=action.report_ref.content_hash
        )
        _require(
            action.representation == action.request.representation
            and action.request.build
            == action.delivery.build
            == outcome.runtime.parser_build
            and action.request.profile_digest
            == outcome.runtime.validation_profile_digest
            and action.request.taxonomy_version == outcome.runtime.taxonomy_version
            and action.request.source_content_hash
            == (
                outcome.integrity.normalized_content_hash
                if action.representation == "normalized"
                else outcome.integrity.archive_member_hash
            )
            and action.request.digest == action.delivery.action_key
            and action.delivery.delivery_revision == outcome.runtime.delivery_revision
            and action.delivery.report_content_hash == action.report_ref.content_hash
            and action.delivery.result_artifact_id
            == action.result_ref.artifact_id
            == result.artifact_id
            and action.result_ref.content_hash == sha256_digest(result)
            and action.report_ref.artifact_id
            == f"sec-parser-action-report-v1:{action.report_ref.content_hash}"
            and action.delivery_ref.content_hash == sha256_digest(action.delivery)
            and result.evidence_marker(action.delivery_ref.content_hash)
            in execution_validation_evidence(report),
            "source_scope_mismatch",
            "Witness parser request, delivery, report or result differs from retained execution",
        )
    _require(
        archive_hash == _POLICY.archive_sha256 == outcome.integrity.archive_hash
        and outcome.integrity.archive_member_hash == _POLICY.primary_sha256,
        "source_hash_mismatch",
        "Original archive or primary hash is outside this exact policy",
    )


def _evaluate_original_disclosures(
    source: FiscalClassificationSource, *, check_deadline: Callable[[], float]
) -> AccountingSupport | AccountingRefusal:
    check_deadline()
    if len(source.archive) > _POLICY.max_archive_bytes:
        raise SnapshotError(
            "FISCAL_ACCOUNTING_BUDGET_EXCEEDED", "Archive byte bound exceeded"
        )
    outcome = source.evidence.outcome
    if len(source.scope.permitted_inputs) > _POLICY.max_observations or (
        isinstance(outcome, FiscalValidationCompleteRefusedV1)
        and (
            len(outcome.claim.report.facts) > _POLICY.max_report_facts
            or len(outcome.claim.report.findings) > _POLICY.max_findings
            or len(outcome.action_refs) > _POLICY.max_actions
            or len(outcome.responses) > _POLICY.max_responses
        )
    ):
        raise SnapshotError(
            "FISCAL_ACCOUNTING_BUDGET_EXCEEDED",
            "Source evidence cardinality bound exceeded",
        )
    archive_hash = hashlib.sha256(source.archive).hexdigest()
    validation_hash = sha256_digest(source.evidence.model_dump(mode="json"))
    scope_hash = source.scope.scope_digest
    witness_hash = sha256_digest(source.witness)
    check_deadline()
    primary_hash = None
    try:
        _check_source(source, archive_hash, validation_hash, witness_hash)
        check_deadline()
        member = read_sec_xbrl_archive(
            source.archive, primary_document=_POLICY.primary, dts_filenames=()
        )[_POLICY.primary]
        check_deadline()
        primary_hash = hashlib.sha256(member).hexdigest()
        _require(
            primary_hash == _POLICY.primary_sha256,
            "source_hash_mismatch",
            "Archive primary member differs from this policy",
        )
        tagged, zeros, link, tables, bridges = _read_disclosures(
            source, member, check_deadline=check_deadline
        )
        check_deadline()
        return AccountingSupport(
            policy=source_accounting_policy_identity(),
            source_evidence_sha256=validation_hash,
            scope_sha256=scope_hash,
            witness_sha256=witness_hash,
            archive_sha256=archive_hash,
            primary_sha256=primary_hash,
            tagged=tagged,
            plain_zeros=zeros,
            link=link,
            tables=tables,
            bridges=bridges,
        )
    except _Refusal as error:
        check_deadline()
        return AccountingRefusal(
            policy=source_accounting_policy_identity(),
            source_evidence_sha256=validation_hash,
            scope_sha256=scope_hash,
            witness_sha256=witness_hash,
            archive_sha256=archive_hash,
            primary_sha256=primary_hash,
            reason=error.reason,
            detail=error.detail,
        )


def evaluate_source_accounting(
    source: FiscalClassificationSource, *, check_deadline: Callable[[], float]
) -> EvaluatedSourceAccounting:
    result = _evaluate_original_disclosures(source, check_deadline=check_deadline)
    check_deadline()
    return EvaluatedSourceAccounting(source, result)
