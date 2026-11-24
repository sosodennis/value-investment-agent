from __future__ import annotations

from dataclasses import dataclass


REGISTERED_HTML_BLOCK_POLICY = "sec-edgar-registered-html-block-representation-v1"


@dataclass(frozen=True)
class HtmlBlockRepresentationRegistration:
    issuer_id: str
    accession_number: str
    primary_document: str
    archive_index_hash: str
    archive_hash: str
    archive_member_hash: str
    scriptless_primary_hash: str
    submission_hash: str
    archive_crlf_count: int
    deleted_lf_offsets: tuple[int, ...]
    proof_digest: str
    concept_type_proof_digest: str
    context_proof_digest: str
    validation_profile_digest: str
    taxonomy_cache_hash: str


REGISTRATIONS = (
    HtmlBlockRepresentationRegistration(
        issuer_id="0000789019",
        accession_number="0001564590-20-034944",
        primary_document="msft-10k_20200630.htm",
        archive_index_hash="4560294b1ced82b917f1a930a775828a261b92174661e0c8c2fdb9dcead2d1d2",
        archive_hash="d1f764a1e8eb0c222ce26dfc9b3ef5cba1cf4a66ded917fc052248f896372516",
        archive_member_hash="47985d3dbaf1c244b78622fb960637e137c7afff506630dfff05fbbb20c7c249",
        scriptless_primary_hash="0e1b83d390e41c0a4dd79630ccec3c9f2bf04309cd94a7990ac4a24fc4a6eba9",
        submission_hash="9d3d278dd79802fe2a2cc8d38b883de9f57a534bb7de4fb88d62933d14b2318f",
        archive_crlf_count=52284,
        deleted_lf_offsets=(
            1763,
            442865,
            454312,
            458286,
            463057,
            472963,
            474107,
            475503,
            477730,
            488131,
            492562,
            495332,
            497927,
            503110,
            505049,
            507829,
            530384,
            534488,
            545867,
            547394,
            605158,
            607197,
            609051,
            616693,
            626456,
            628487,
            629851,
            633043,
            634199,
            636581,
            637717,
            640345,
            643346,
            645847,
            649607,
            650946,
            652985,
            655581,
            656752,
            657779,
            659112,
            660486,
            662966,
            664062,
            666579,
            676736,
            678624,
            685006,
            686628,
            687750,
            692209,
            693314,
            699247,
            700395,
            705309,
            707581,
            708808,
            719401,
            751065,
            972172,
            973316,
            1491489,
            1492945,
            1494270,
            1495773,
            1498080,
            1499303,
            1626600,
            1632389,
            1637511,
            1645651,
            2036093,
            2432447,
            2434282,
            2444723,
            2519163,
            2520632,
            2521760,
            2524797,
            2526089,
            2528553,
            2530035,
            2538182,
            2545563,
            2549819,
            2556561,
            2558431,
            2562404,
            2566077,
            2567384,
            3401236,
            3632067,
            3822137,
            4156276,
            4159228,
            4208348,
            4295239,
            4429152,
            4651139,
            4834295,
            4835457,
            4942484,
            4943568,
            4946393,
            4949259,
            5003321,
            5051267,
            5053341,
            5273358,
            5280432,
            5281720,
            5284833,
            5321001,
            5394962,
            5503999,
            5532973,
            5560542,
            5589449,
            5620699,
            5649349,
            5670340,
            5726689,
            5730100,
            5732869,
            5754398,
            5770165,
            5772370,
            5773481,
            5937543,
            6103958,
            6105994,
            6111556,
            6151477,
            6152521,
            6159388,
            6593086,
        ),
        proof_digest="889ae2c1880b4e1bef1c75944e28cda911a2ce0a1315e30969b72e202f3b1ae7",
        concept_type_proof_digest="eca9c22e5ae42ecac63c0b3ac45217d3ad2c53dbec3c1c813cbb187e3a0ec2e3",
        context_proof_digest="c60f34a5fc4926adcbc35332d22560ae7a78ed31a9d9e82c30c580f365c61dca",
        validation_profile_digest="94966eb7ad11e6fd2c20776328a92fe2baf46c8fe1eb9b6d950a397e84958247",
        taxonomy_cache_hash="fbcd82b406a2420f37bf17c7afc8baa823e7cfadd2308ccb8bfecf88648a9691",
    ),
)


def registered_html_block_representation(
    archive_member_hash: str,
) -> HtmlBlockRepresentationRegistration | None:
    return next(
        (
            item
            for item in REGISTRATIONS
            if item.archive_member_hash == archive_member_hash
        ),
        None,
    )
