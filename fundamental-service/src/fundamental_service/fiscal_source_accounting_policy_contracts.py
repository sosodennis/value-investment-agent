from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable
from time import monotonic
from typing import Any, Literal, Self

from pydantic import (
    ConfigDict,
    ModelWrapValidatorHandler,
    PrivateAttr,
    TypeAdapter,
    ValidationInfo,
    model_validator,
)

from .contracts import StrictModel
from .fiscal_candidate_contracts import FiscalSourceUseScopeV1
from .fiscal_classification_contracts import FiscalSourceAccountingReviewV1
from .fiscal_classification_source import FiscalClassificationSource
from .fiscal_focus_witness import SignedFiscalDiagnosticFocusWitnessV1
from .fiscal_source_accounting_policy import (
    _POLICY,
    AccountingSupport,
    AccountingVerdict,
    EvaluatedSourceAccounting,
    _evaluate_original_disclosures,
    _load_resources,
)
from .fiscal_validation_contracts import FiscalOriginalValidationEvidenceV1
from .serialization import canonical_bytes
from .snapshots import SnapshotError


def _budget(condition: bool, message: str) -> None:
    if not condition:
        raise SnapshotError("FISCAL_ACCOUNTING_BUDGET_EXCEEDED", message)


def _local_check() -> Callable[[], float]:
    end = monotonic() + _POLICY.replay_seconds

    def check() -> float:
        remaining = end - monotonic()
        if remaining <= 0:
            raise SnapshotError(
                "DEADLINE_EXCEEDED", "Accounting record replay exceeded its deadline"
            )
        return remaining

    return check


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON property in accounting record")
    return result


def _nonfinite(value: str) -> None:
    raise ValueError(f"Non-finite JSON number {value}")


_JSON_STRUCTURE = re.compile(rb'"(?:[^"\\]++|\\.)*+"|[{}\[\],:]')
_CARDINALITY = {
    "facts": _POLICY.max_report_facts,
    "findings": _POLICY.max_findings,
    "action_refs": _POLICY.max_actions,
    "parser_action_refs": _POLICY.max_actions,
    "actions": _POLICY.max_actions,
    "responses": _POLICY.max_responses,
    "source_responses": _POLICY.max_responses,
    "permitted_inputs": _POLICY.max_observations,
}


def _json(raw: bytes, check: Callable[[], float], *, outer: bool = False) -> Any:
    check()
    depth = 0
    for index, token in enumerate(_JSON_STRUCTURE.finditer(raw)):
        if index % 2048 == 0:
            check()
        _budget(
            index < _POLICY.max_json_nodes * 4, "Accounting JSON token bound exceeded"
        )
        first = raw[token.start()]
        if first in (123, 91):
            depth += 1
            _budget(depth <= _POLICY.max_depth, "Accounting JSON depth bound exceeded")
        elif first in (125, 93):
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced accounting JSON")
    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite
    )
    _check_structure(value, check, outer=outer)
    return value


def _check_structure(
    value: Any, check: Callable[[], float], *, outer: bool = False
) -> None:
    remaining = _POLICY.max_json_nodes

    def visit(item: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining % 2048 == 0:
            check()
        _budget(
            remaining >= 0 and depth <= _POLICY.max_depth,
            "Accounting JSON structure exceeds its budget",
        )
        if isinstance(item, dict):
            for name, child in item.items():
                _budget(len(name) <= 256, "Accounting JSON key exceeds its limit")
                if name in _CARDINALITY and isinstance(child, (tuple, list)):
                    _budget(
                        len(child) <= _CARDINALITY[name],
                        f"Accounting {name} exceeds its cardinality limit",
                    )
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, str):
            _budget(
                outer or len(item) <= _POLICY.max_scalar_bytes,
                "Accounting JSON scalar exceeds its limit",
            )
        elif type(item) not in (bool, int, float, type(None)):
            raise ValueError("Accounting replay accepts JSON values only")

    visit(value, 0)
    check()


def _decode(value: str, limit: int) -> bytes:
    _budget(
        len(value) <= 4 * ((limit + 2) // 3),
        "Encoded accounting input exceeds its byte limit",
    )
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Invalid base64 accounting input") from error
    _budget(len(raw) <= limit, "Decoded accounting input exceeds its byte limit")
    if base64.b64encode(raw).decode("ascii") != value:
        raise ValueError("Noncanonical base64 accounting input")
    return raw


class _FrozenRecord(StrictModel):
    model_config = ConfigDict(
        strict=True, frozen=True, extra="forbid", revalidate_instances="always"
    )


class _OriginalBytes(_FrozenRecord):
    validation_json_b64: str
    witness_json_b64: str
    scope_json_b64: str
    archive_zip_b64: str

    def source(self, check: Callable[[], float]) -> FiscalClassificationSource:
        check()
        media = (
            (self.validation_json_b64, _POLICY.max_validation),
            (self.witness_json_b64, _POLICY.max_witness),
            (self.scope_json_b64, _POLICY.max_scope),
            (self.archive_zip_b64, _POLICY.max_capsule_archive),
        )
        for value, limit in media:
            _budget(
                len(value) <= 4 * ((limit + 2) // 3),
                "Encoded accounting input exceeds its byte limit",
            )
        validation_raw, witness_raw, scope_raw, archive = (
            _decode(value, limit) for value, limit in media
        )
        for original in (validation_raw, witness_raw, scope_raw):
            _json(original, check)
        _load_resources()
        check()
        evidence = FiscalOriginalValidationEvidenceV1.model_validate_json(
            validation_raw
        )
        if canonical_bytes(evidence.model_dump(mode="json")) != validation_raw:
            raise ValueError("Validation input differs from owner canonical JSON")
        check()
        witness = SignedFiscalDiagnosticFocusWitnessV1.model_validate_json(witness_raw)
        if canonical_bytes(witness) != witness_raw:
            raise ValueError("Witness input differs from owner canonical JSON")
        check()
        scope = FiscalSourceUseScopeV1.model_validate_json(scope_raw)
        if canonical_bytes(scope) != scope_raw:
            raise ValueError("Scope input differs from owner canonical JSON")
        check()
        return FiscalClassificationSource(scope, evidence, witness, archive)


class AccountingReplayRecordV3(_FrozenRecord):
    protocol: Literal["fundamental.fiscal-accounting-replay.v3"]
    inputs: _OriginalBytes
    result: AccountingVerdict
    _scope: FiscalSourceUseScopeV1 = PrivateAttr()

    @model_validator(mode="wrap")
    @classmethod
    def replay(
        cls, raw: Any, handler: ModelWrapValidatorHandler[Self], info: ValidationInfo
    ) -> Self:
        check = (
            info.context["check_deadline"]
            if info.context is not None and "check_deadline" in info.context
            else _local_check()
        )
        check()
        if isinstance(raw, cls):
            return TypeAdapter(cls).validate_json(
                raw.model_dump_json(), strict=True, context={"check_deadline": check}
            )
        if not isinstance(raw, dict) or not isinstance(raw.get("result"), dict):
            raise ValueError("Accounting replay requires an explicit JSON result")
        claim = raw["result"]
        _check_structure(claim, check)
        claimed = canonical_bytes(claim)
        _budget(
            len(claimed) <= _POLICY.max_claim,
            "Claimed accounting result exceeds its byte limit",
        )
        if (
            set(raw) != {"protocol", "inputs", "result"}
            or raw["protocol"] != "fundamental.fiscal-accounting-replay.v3"
        ):
            raise ValueError("Unexpected accounting replay fields or version")
        inputs = _OriginalBytes.model_validate(raw["inputs"], strict=True)
        source = inputs.source(check)
        actual = _evaluate_original_disclosures(source, check_deadline=check)
        if claimed != canonical_bytes(actual.model_dump(mode="json")):
            raise ValueError(
                "Claimed accounting result differs from complete original replay"
            )
        parsed = handler({**raw, "result": actual})
        parsed._scope = source.scope
        check()
        return parsed

    def review(self) -> FiscalSourceAccountingReviewV1 | None:
        if isinstance(self.result, AccountingSupport):
            return self.result._review(self._scope)
        return None


def encode_accounting_record(
    live: EvaluatedSourceAccounting, *, check_deadline: Callable[[], float]
) -> bytes:
    check_deadline()
    source = live._source
    originals = (
        (
            "validation_json_b64",
            canonical_bytes(source.evidence.model_dump(mode="json")),
            live.result.source_evidence_sha256,
            _POLICY.max_validation,
        ),
        (
            "witness_json_b64",
            canonical_bytes(source.witness),
            live.result.witness_sha256,
            _POLICY.max_witness,
        ),
        (
            "scope_json_b64",
            canonical_bytes(source.scope),
            live.result.scope_sha256,
            _POLICY.max_scope,
        ),
        (
            "archive_zip_b64",
            source.archive,
            live.result.archive_sha256,
            _POLICY.max_capsule_archive,
        ),
    )
    encoded = {}
    for field, raw, expected, limit in originals:
        check_deadline()
        _budget(len(raw) <= limit, "Original accounting input exceeds its record limit")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(
                "Original input changed after the live accounting evaluation"
            )
        encoded[field] = base64.b64encode(raw).decode("ascii")
    result = live.result.model_dump(mode="json")
    _budget(
        len(canonical_bytes(result)) <= _POLICY.max_claim,
        "Accounting result exceeds its record limit",
    )
    record = canonical_bytes(
        {
            "protocol": "fundamental.fiscal-accounting-replay.v3",
            "inputs": encoded,
            "result": result,
        }
    )
    _budget(
        len(record) <= _POLICY.max_outer, "Accounting record exceeds its byte limit"
    )
    check_deadline()
    return record


def read_accounting_record(
    raw: bytes, *, check_deadline: Callable[[], float]
) -> AccountingReplayRecordV3:
    check_deadline()
    _budget(len(raw) <= _POLICY.max_outer, "Accounting record exceeds its byte limit")
    _json(raw, check_deadline, outer=True)
    return TypeAdapter(AccountingReplayRecordV3).validate_json(
        raw, strict=True, context={"check_deadline": check_deadline}
    )


class _PreparedAccountingRecordV3(_FrozenRecord):
    protocol: Literal["fundamental.fiscal-accounting-replay.v3"]
    inputs: _OriginalBytes
    result: AccountingVerdict


def read_prepared_accounting_record(
    raw: bytes,
    source: FiscalClassificationSource,
    *,
    check_deadline: Callable[[], float],
) -> _PreparedAccountingRecordV3:
    check_deadline()
    _budget(len(raw) <= _POLICY.max_outer, "Accounting record exceeds its byte limit")
    _json(raw, check_deadline, outer=True)
    record = _PreparedAccountingRecordV3.model_validate_json(raw, strict=True)
    expected = _OriginalBytes(
        validation_json_b64=base64.b64encode(
            canonical_bytes(source.evidence.model_dump(mode="json"))
        ).decode("ascii"),
        witness_json_b64=base64.b64encode(canonical_bytes(source.witness)).decode(
            "ascii"
        ),
        scope_json_b64=base64.b64encode(canonical_bytes(source.scope)).decode("ascii"),
        archive_zip_b64=base64.b64encode(source.archive).decode("ascii"),
    )
    if (
        record.inputs != expected
        or canonical_bytes(record.model_dump(mode="json")) != raw
    ):
        raise ValueError("Prepared accounting inputs differ from current source bytes")
    _load_resources()
    check_deadline()
    return record
