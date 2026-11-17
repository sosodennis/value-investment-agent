# Build identity checkpoint

Implementation `97d1d8a2206c1888a1fad320961f0c3d87682fd5` separates stable
computation identity from exact execution evidence and excludes host Python
bytecode at both Docker build context roots. Runtime dependency hashing is
unchanged. Forced host bytecode recompilation followed by rebuilding produced
the same image, `sha256:3b2d39cd39b2c608588b95b44cdfe17bc772c394e0c9a0ae92d5abca69c4a72f`,
with no `.pyc` under `/app/src`.

The exact implementation full Fundamental suite passed: 4,837 tests, 20 skips,
625.13 seconds. Pinned Ruff/format, 27 changed source files' types, architecture
guard, caller boundary and the applicable Service calculator release gate pass.
Independent source review found no confirmed blocker in the incremental diff.
Skipped resource tests and the legacy skipped release job are not passes.

The SEC-enabled service preflight matches the exact image, 183 installed source
files, source digest `d914d0fcc8d591c751b5989dfb671e7ecd419e232c0a1660d6294ca306fe62b6`,
and the recorded project-owned resources. Its output digest is
`c484b22ace24a414804122386360bd2ca683f9a4c66d8829d826e0ad8f0d0dee`.
Complete logs and manifests remain outside Git in this issue's audit directory.

This is a WIP checkpoint. First preparation of the bytecode-free build, final
five-pair numerical/API replays, cross-delivery body reuse and recovery/refusal
acceptance are incomplete. The earlier test-only rebuild unexpectedly reparsed
because host bytecode changed the immutable build; its successful numerical run
is retained with a scope correction, not used as cross-delivery cache evidence.
MSFT remains provisional, uncalibrated what-if; the history threshold stays null.
