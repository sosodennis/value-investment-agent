from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from fundamental_service import history_market_evidence as market
from fundamental_service.contracts import SourceRole
from fundamental_service.history_replay_inputs import DEFAULT_DIRECTORY
from fundamental_service.public_source import PublicSourceAdapter
from fundamental_service.snapshots import CapturedSource, SnapshotError

SOURCE_MANIFEST = (
    DEFAULT_DIRECTORY
    / "source_manifest"
    / "83909f9be4368fe1453d7707902b8b70009dfe62727e27db4c27f94b1f9cc020.json.gz"
)


def _install_source(
    monkeypatch: pytest.MonkeyPatch, calls: list[str], *, failure: bool = False
) -> None:
    def capture(
        _self: PublicSourceAdapter,
        source_id: str,
        uri: str,
        *,
        available_at: datetime,
    ) -> CapturedSource:
        calls.append(uri)
        if failure:
            raise SnapshotError("SOURCE_HTTP_ERROR", "fixture unavailable")
        vintage = date.fromisoformat(parse_qs(urlsplit(uri).query)["vintage_date"][0])
        return CapturedSource(
            source_id=source_id,
            uri=uri,
            role=SourceRole.MACRO,
            content=(
                f"observation_date,DGS10_{vintage:%Y%m%d}\n{vintage},2.13\n"
            ).encode(),
            media_type="text/csv",
            http_status=200,
            available_at=available_at,
            captured_at=datetime(2026, 11, 10, tzinfo=UTC),
        )

    monkeypatch.setattr(PublicSourceAdapter, "capture", capture)
    monkeypatch.setenv("FUNDAMENTAL_SEC_USER_AGENT", "Fixture fixture@example.com")


def test_fixed_decisions_share_vintages_and_repeat_without_requests_or_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_source(monkeypatch, calls)
    first = market.capture_market_evidence(
        source_manifest_path=SOURCE_MANIFEST, output_directory=tmp_path
    )
    assert first["selected_issuer_count"] == 100
    assert first["downloads"] == first["source_count"] == 35
    assert first["observed_candidate_count"] == 35
    original = {path: path.read_bytes() for path in tmp_path.rglob("*.gz")}
    monkeypatch.delenv("FUNDAMENTAL_SEC_USER_AGENT")

    def reject_replace(*args: object) -> None:
        raise AssertionError("unchanged capture must not replace artifacts")

    monkeypatch.setattr(market.os, "replace", reject_replace)
    repeat = market.capture_market_evidence(
        source_manifest_path=SOURCE_MANIFEST, output_directory=tmp_path
    )
    assert len(calls) == 35
    assert repeat["downloads"] == 0
    assert repeat["wrote"] is False
    assert repeat["output_digest"] == first["output_digest"]
    assert original == {path: path.read_bytes() for path in original}


def test_frozen_failures_keep_all_issuers_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _install_source(monkeypatch, calls, failure=True)
    first = market.capture_market_evidence(
        source_manifest_path=SOURCE_MANIFEST, output_directory=tmp_path
    )
    repeat = market.capture_market_evidence(
        source_manifest_path=SOURCE_MANIFEST, output_directory=tmp_path
    )
    assert first["selected_issuer_count"] == repeat["selected_issuer_count"] == 100
    assert first["observed_candidate_count"] == 0
    assert len(calls) == 35
    assert repeat["wrote"] is False


def test_rate_retains_vintage_and_converts_percent_without_filling_weekend() -> None:
    result = market._observation(
        b"observation_date,DGS10_20160111\n2016-01-08,2.13\n2016-01-11,\n",
        date(2016, 1, 11),
    )
    assert result["value"] == "0.0213"
    assert result["observation_date"] == "2016-01-08"
    assert result["available_at"] == "2016-01-12T00:00:00+00:00"


@pytest.mark.parametrize(
    "content",
    (
        b"observation_date,DGS10_20260111\n2016-01-08,2.13\n",
        b"observation_date,DGS10_20160111\n2016-01-12,2.13\n",
        b"observation_date,DGS10_20160111\n2016-01-08,NaN\n",
        b"observation_date,DGS10_20160111\n2016-01-08,2.13\n2016-01-08,2.15\n",
        b"observation_date,DGS10_20160111\n2016-01-08,\n",
        b"<html>unavailable</html>",
    ),
)
def test_incorrect_vintage_future_invalid_and_conflicting_rates_are_rejected(
    content: bytes,
) -> None:
    with pytest.raises(ValueError):
        market._observation(content, date(2016, 1, 11))


def test_tampered_source_fails_without_requesting_a_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gzip

    calls: list[str] = []
    _install_source(monkeypatch, calls)
    market.capture_market_evidence(
        source_manifest_path=SOURCE_MANIFEST, output_directory=tmp_path
    )
    path = sorted((tmp_path / "source_index").glob("*.gz"))[0]
    receipt, _ = gzip.decompress(path.read_bytes()).split(b"\n", 1)
    path.write_bytes(gzip.compress(receipt + b"\nchanged", mtime=0))
    with pytest.raises(ValueError, match="digest mismatch"):
        market.capture_market_evidence(
            source_manifest_path=SOURCE_MANIFEST, output_directory=tmp_path
        )
    assert len(calls) == 35
