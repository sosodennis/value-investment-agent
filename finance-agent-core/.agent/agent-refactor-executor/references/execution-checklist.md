# Refactor Execution Checklist

Use this checklist before marking any slice as complete.

## 1) Scope
- Slice objective is clear and bounded.
- Out-of-scope files remain untouched.
- Slice size is `small` or `medium`.

## 2) Verifiability
- Slice has at least one independent validation gate.
- Validation command(s) and expected result are defined.

## 3) Safety
- Rollback point is identified.
- Compatibility impact is assessed.
- No hidden dependency drift introduced.

## 4) Compliance
- Architecture standards check is run on changed paths.
- No blocking hard-rule violations remain.

## 5) Handoff
- Slice summary is recorded.
- Residual risks are documented.
- Next slice entry condition is explicit.
