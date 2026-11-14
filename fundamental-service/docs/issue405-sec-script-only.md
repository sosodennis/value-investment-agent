# Exact SEC edge-script removal

The existing `sec-edgar-akamai-trailing-script-v2` relation removes one supported
terminal edge script and one added LF. Some accession ZIP originals already end
in LF: removing the script alone reproduces the original bytes. The service
records that separate relation as `sec-edgar-akamai-script-only-v1`.

Both relations require the existing exact Akamai response header, supported
terminal script/HTML closing shape, matching original accession, unique archive
member, and index-confirmed script-free size. The new relation additionally
requires every script-free response byte to equal the archive member, including
its terminal LF. It removes only the script, retains that exact byte range and
hash, and binds raw/index/ZIP/member hashes and offsets to the rule signature.
The prior v2 rule signature and outputs retain their existing bytes.

This does not permit arbitrary whitespace, number, script or document changes.
The parser receives the unchanged archive member. Offline parsing, archive fact
comparison, and EFM/DQC gates still apply. A successful integrity comparison
establishes neither complete financial scope nor reviewed mappings, release
approval, caller approval or valuation eligibility.

The initial real probe is NVE CIK `0000724910`, original
`0001376474-23-000283`, accepted `2023-05-03T20:05:15Z`, cutoff
`2025-04-01T00:00:00Z`. Its raw response hash is
`26d95888105590690531f4b3c4da8ca910e6aa4e315f6372ed51c55459b0b05c`;
ZIP hash is `2f1cee595af8ed3e1546b611b21927a8c3ca339254f527ea2e7caf8313ee8112`.
The initial failed integrity probe remains outside Git. Exact implementation,
real parser outcomes and repeat digests belong in the #361 acceptance checkpoint
before this change is considered delivered. Refs #405 and #361.
