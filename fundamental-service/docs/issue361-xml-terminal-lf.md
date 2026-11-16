# Historical XML terminal LF evidence

Actual fixed-cohort validation at `0b51372a4c90370154cd52ace3899141b012090a`
found original 2016 responses whose only difference from their same-accession
XBRL ZIP member is one final LF byte. Examples are accessions
`0001282637-16-000028`, `0001000180-16-000068`, `0001025953-16-000180` and
`0001452575-16-000063`. The SEC index declares the direct response size; the
ZIP index independently declares the exact ZIP size. Each direct body equals
the original member plus `0a`, after the closing XBRL root element. These are
representation mismatches, not proof of different financial facts.

The separate `sec-edgar-xbrl-xml10-terminal-lf-v1` integrity rule accepts exactly
that relation for XML 1.0 XBRL instances. It retains raw/index/ZIP/member hashes,
the removed byte's offset and digest, and an accession-bound rule signature.
It passes the unchanged archived instance to the existing offline parser and
EFM/DQC gates. The existing normalized-versus-archive fact/finding comparison
still runs. No filing, accounting fact, mapping, policy, release or forecast is
approved by this byte-level relation.

The rule rejects an incorrect declared size, value changes, multiple added
newlines, spaces, unsupported XML versions/root namespaces, DTDs and non-XML
primary documents. Its identity and rule remain separate from the CRLF policy.
Unrecognized differences remain refused.

The [W3C XML 1.0 specification](https://www.w3.org/TR/REC-xml/) defines production
1 as `document ::= prolog element Misc*` and production 27 as
`Misc ::= Comment | PI | S`. Thus the proved single LF after the document
element lies outside its content. Previously captured official specification
bytes have SHA-256
`f58a4b9e1e5b8bac13fb55c4e5c7c8c5e2c176aa45ee68e2f1ab2498511927ec`.
This is parser compatibility research and never threshold ground truth.

## Combined CRLF and final LF representation

The complete fixed589 diagnostic retained210 source-size refusals. An offline
comparison of those same original receipts found23 responses equal to the ZIP
member after replacing each CRLF pair with LF and appending exactly one LF.
For example, accession `0001564590-17-002567`, primary `lxu-20161231.xml`, has
direct hash `0b6baaeaccefc44f545495f750c4236041acffbfdc714b1501d7bd80ddbd509d`
and ZIP hash `8f84a6669017f08e13f373997f432900e2f49050712a60b47c984c30ad2e50fc`.
The previous two rules each handled one delta, so neither accepted this exact
composition. A focused regression reproduced `SOURCE_ARCHIVE_SIZE_MISMATCH`
before the fix.

The independent versioned rule
`sec-edgar-xbrl-xml10-line-ends-terminal-lf-v1` requires both indexed response
sizes, one accession-matched member, XML1.0/XBRL, no DTD, no CR in the direct
body, at least one CRLF pair in the member, and its final closing root with no
following whitespace. Every direct byte must equal the declared transformation.
The signature binds all original hashes, accession, filename, inserted CR count
and the single removed LF offset in the direct response. The parser still
receives the unchanged ZIP member; no financial fact text is trimmed or repaired.

The XML1.0 basis is the same document/Misc grammar above together with
[section2.11](https://www.w3.org/TR/REC-xml/#sec-line-ends), which requires CRLF
normalization before parsing. This rule does not perform generic XML
canonicalization. All other187 size refusals remain refused, including changed
comment text, internal whitespace and potentially changed fact strings. Value
changes, extra whitespace/newlines, bad sizes, wrong media/namespace/version and
DTDs remain blocked in regression tests. Successful byte-integrity assessment
still grants no parser/DQC, identity, mapping, policy, release or forecast approval.
