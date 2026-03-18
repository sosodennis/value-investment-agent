# T33 Specification

## Goal
Upgrade technical alerts from simple threshold notifications into enterprise-grade policy alerts with typed metadata, evidence references, lifecycle semantics, and quality gating.

## Slice 1 Scope
- Add typed alert policy/evidence/summary contracts.
- Project existing RSI / FD / breakout alerts through the new policy contract.
- Add deterministic quality-gate semantics using currently available artifact metadata.
- Align frontend alert parser/types and generated API contract in the same slice.

## Non-Goals
- Do not add new composite multi-artifact alert policies yet.
- Do not change frontend UI rendering in this slice.
- Do not rework the overall technical workflow ordering.
