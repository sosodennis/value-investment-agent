import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

from fundamental_service.arelle_parser import (
    ArelleValidationProfileV1,
    _directory_hash,
    fact_semantic_digest,
    parse_filing_offline,
)
from fundamental_service.contracts import SourceRole
from fundamental_service.sec_integrity import assess_filing_response
from fundamental_service.snapshots import CapturedSource


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--edgar-plugin-dir", type=Path, required=True)
    parser.add_argument("--xule-plugin-dir", type=Path, required=True)
    parser.add_argument("--dqc-ruleset-path", type=Path, required=True)
    parser.add_argument("--taxonomy-cache-dir", type=Path, required=True)
    args = parser.parse_args()

    def read_object(digest: str, suffix: str) -> bytes:
        payload = (args.evidence_dir / f"{digest}.{suffix}").read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digest
        return payload

    raw = read_object(
        "0bb3e310d6aafc4c2aa9f215d79f7b819b7862cc119ed6fe26c3b604ce75d536",
        "bin",
    )
    archive_bytes = read_object(
        "5a7653632f53c2529c4da82d25043fc52f05bfbe536837345aa5904560d92a82",
        "bin",
    )
    index_bytes = read_object(
        "5692bbfccc76991d2cba6f4ddf2a8db9487dfce51ac5dded0b2607660a65a966",
        "json",
    )
    now = datetime.now(timezone.utc)
    accession = "0000950170-24-087843"
    base = "https://www.sec.gov/Archives/edgar/data/789019/000095017024087843"
    assessment = assess_filing_response(
        raw_response=CapturedSource(
            "sec-filing",
            f"{base}/msft-20240630.htm",
            SourceRole.FILING,
            raw,
            "text/html",
            200,
            now,
            accession_number=accession,
            response_headers=(("x-akamai-transformed", "0 - 0 -"),),
            received_size=len(raw),
        ),
        archive_index=CapturedSource(
            "sec-filing-index",
            f"{base}/index.json",
            SourceRole.REFERENCE,
            index_bytes,
            "application/json",
            200,
            now,
            accession_number=accession,
        ),
        archive=CapturedSource(
            "sec-filing-archive",
            f"{base}/{accession}-xbrl.zip",
            SourceRole.FILING,
            archive_bytes,
            "application/zip",
            200,
            now,
            accession_number=accession,
        ),
    )
    assert assessment.relation == "normalized"
    assert assessment.normalization_policy_id == "sec-edgar-akamai-trailing-script-v2"
    assert assessment.normalized_content_hash == assessment.archive_member_hash
    assert len(raw) == 6_861_030
    assert assessment.archive_index_entry["size"] == "6860911"
    assert len(assessment.archive_member) == 6_860_910
    assert [item.model_dump(mode="json") for item in assessment.removed_ranges] == [
        {
            "start": 6_860_895,
            "end": 6_861_014,
            "content_hash": (
                "cecc8aa8a16de673292c5bda6e96fab070080592ead3fb82fd1e40286c3172db"
            ),
        },
        {
            "start": 6_861_029,
            "end": 6_861_030,
            "content_hash": (
                "01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b"
            ),
        },
    ]

    with tempfile.TemporaryDirectory(
        prefix="issue312-retained-4fe205a3-replay-"
    ) as tmp:
        root = Path(tmp)
        edgar = root / "EDGAR"
        xule = root / "xule"
        dqc = root / "dqc-us-ruleset.zip"
        edgar.symlink_to(args.edgar_plugin_dir, target_is_directory=True)
        xule.symlink_to(args.xule_plugin_dir, target_is_directory=True)
        dqc.symlink_to(args.dqc_ruleset_path)
        profile = ArelleValidationProfileV1(
            profile_id="sec-efm-us-dqc-v31.0.3",
            validation_mode="sec-efm-dqc",
            edgar_plugin_dir=edgar,
            xule_plugin_dir=xule,
            dqc_ruleset_path=dqc,
            edgar_plugin_sha256=_directory_hash(args.edgar_plugin_dir),
            xule_plugin_sha256=_directory_hash(args.xule_plugin_dir),
            dqc_ruleset_sha256=hashlib.sha256(
                args.dqc_ruleset_path.read_bytes()
            ).hexdigest(),
        )
        assert profile.digest() == (
            "639140b39584b3ee3276f09a011403dec911efe41ea1b98773f5f770bd5200d4"
        )

        archive_path = args.evidence_dir / (
            "5a7653632f53c2529c4da82d25043fc52f05bfbe536837345aa5904560d92a82.bin"
        )
        with ZipFile(archive_path) as package:
            canonical = package.read("msft-20240630.htm")
            schema = package.read("msft-20240630.xsd")

        reports = []
        for name, filing in (
            ("normalized", assessment.normalized_content),
            ("canonical", canonical),
        ):
            folder = root / name
            folder.mkdir()
            filing_path = folder / "msft-20240630.htm"
            filing_path.write_bytes(filing)
            (folder / "msft-20240630.xsd").write_bytes(schema)
            report = parse_filing_offline(
                filing_path,
                profile=profile,
                taxonomy_version="us-gaap-2023-2024",
                taxonomy_cache_dir=args.taxonomy_cache_dir,
                source_content_hash=hashlib.sha256(filing).hexdigest(),
            )
            assert report.validation_engines == ("sec-efm", "dqc-us")
            assert report.validation_evidence == (
                "strict-sec-efm-profile-selected",
                "dqc-dqcrt-checks-completed",
            )
            assert report.blocking_finding_codes() == ()
            assert report.network_attempt_count == 0
            reports.append(report)

    normalized, canonical_report = reports
    digest = fact_semantic_digest(normalized)
    assert len(normalized.facts) == len(canonical_report.facts) == 1856
    assert digest == fact_semantic_digest(canonical_report)
    assert digest == "c1a098e547276a804299bd16e387f5d1967696b34a66786cc429e6815850361d"
    print(
        json.dumps(
            {
                "facts": len(normalized.facts),
                "semantic_digest": digest,
                "engines": normalized.validation_engines,
                "findings": len(normalized.findings),
                "blocking_findings": normalized.blocking_finding_codes(),
                "network_attempt_count": normalized.network_attempt_count,
                "profile_id": normalized.validation_profile.profile_id,
                "profile_digest": normalized.validation_profile_digest,
                "taxonomy_cache_hash": normalized.taxonomy_cache_hash,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
