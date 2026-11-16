"""Synthetic policy and HTTP bytes exercise Yahoo capture and formal admission."""

from datetime import datetime, timedelta
from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

import pytest

from fundamental_service.contracts import IdentityV1
from fundamental_service.public_acquisition import PublicSourceAcquisitionRequestV1
from fundamental_service.public_admission import (
    PublicQuoteSelectionV1,
    PublicSourceAdmission,
    PublicSourceAdmissionRequestV1,
)
from fundamental_service.quote_capture import (
    YAHOO_TERMS_SOURCE,
    quote_preparation_source_adapter,
)
from fundamental_service.quote_source_plan import AutomaticDailyQuoteRequestTemplateV1
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.replay import ArtifactStore
from fundamental_service.source_admission import (
    SourceUsePolicyV1,
    SourceUseRuleV1,
    TermsRequirementV1,
)
from test_public_acquisition import acquisition, inventory
from test_public_source import FakeResponse
from test_yahoo_quote_source import CAPTURE, PROFILE, SOURCE, TERMS, URI, raw_response

TERMS_BYTES = b"Synthetic fixture authorization only, not Yahoo permission."


def policy():
    return SourceUsePolicyV1(
        policy_version="synthetic-yahoo-source-use-v1",
        rules=(
            SourceUseRuleV1(
                rule_id="synthetic-yahoo-grant",
                provider_id=SOURCE,
                metric_id="common_share.price",
                population="common-share",
                source_id=SOURCE,
                source_version=PROFILE,
                terms_reference=TERMS,
                permitted_uses=("valuation_preparation",),
                terms=(
                    TermsRequirementV1(
                        uri=TERMS, content_sha256=sha256(TERMS_BYTES).hexdigest()
                    ),
                ),
                required_notices=("Synthetic authorization",),
                basis="Synthetic fixture only",
            ),
        ),
    )


def template():
    return AutomaticDailyQuoteRequestTemplateV1(
        source_id=SOURCE,
        uri_template=(
            "https://query2.finance.yahoo.com/v8/finance/chart/{security_id}"
            "?period1={observation_start_epoch}&period2={observation_end_epoch}"
            "&interval=1d&events=div,splits,capitalGains"
        ),
        source_profile=PROFILE,
        terms_reference=TERMS,
    )


@pytest.mark.parametrize(
    "valuation,start,end",
    [
        (
            "2026-11-14T12:00:00+00:00",
            "2026-11-13T05:00:00+00:00",
            "2026-11-14T05:00:00+00:00",
        ),
        (
            "2026-11-16T12:00:00+00:00",
            "2026-11-13T05:00:00+00:00",
            "2026-11-14T05:00:00+00:00",
        ),
        (
            "2026-03-09T12:00:00+00:00",
            "2026-03-06T05:00:00+00:00",
            "2026-03-07T05:00:00+00:00",
        ),
        (
            "2026-03-10T12:00:00+00:00",
            "2026-03-09T04:00:00+00:00",
            "2026-03-10T04:00:00+00:00",
        ),
    ],
)
def test_epoch_template_uses_verified_security_and_new_york_day(valuation, start, end):
    identity = IdentityV1(
        issuer_id="0000724910",
        issuer_name="Synthetic identity",
        domicile="US",
        reporting_basis="us-gaap",
        security_id="NVEC",
        share_class="common",
        currency="USD",
    )
    request, selection = template().render(
        identity=identity, valuation_at=datetime.fromisoformat(valuation)
    )
    query = parse_qs(urlsplit(request.uri).query)
    assert query["period1"] == [str(int(datetime.fromisoformat(start).timestamp()))]
    assert query["period2"] == [str(int(datetime.fromisoformat(end).timestamp()))]
    assert request.uri.startswith(
        "https://query2.finance.yahoo.com/v8/finance/chart/NVEC?"
    )
    assert selection.as_of == datetime.fromisoformat(start)
    assert selection.issuer_id == identity.issuer_id


@pytest.mark.parametrize(
    "fields",
    [
        "{security_id}/{observation_start_epoch}",
        "{security_id}/{observation_end_epoch}",
        "{security_id}/{observation_date}/{observation_start_epoch}/{observation_end_epoch}",
        "{security_id}/{observation_start_epoch}/{unknown}",
    ],
)
def test_partial_or_mixed_date_formats_are_rejected(fields):
    with pytest.raises(ValueError, match="one date format"):
        AutomaticDailyQuoteRequestTemplateV1.model_validate(
            {
                **template().model_dump(),
                "uri_template": "https://example.test/" + fields,
            }
        )


def test_saved_sec_original_compiles_the_yahoo_template_without_a_manual_plan(
    tmp_path, monkeypatch
):
    from fundamental_service.original_source_plan import AutomaticQuoteSourceTemplateV1
    from test_original_preparation import case, execute
    from test_original_source_plan import _terms_request, compiler_case, configuration

    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    source_policy = policy()
    config = configuration().model_copy(
        update={
            "quote_source_template": AutomaticQuoteSourceTemplateV1(
                request=template(),
                terms=(_terms_request(YAHOO_TERMS_SOURCE, TERMS),),
                source_use_policy_version=source_policy.policy_version,
                source_use_policy_digest=source_policy.digest,
            )
        }
    )
    compiler, input_request = compiler_case(value, prepared, config)
    calls = value.state.provider_calls, value.state.parser_calls
    result, receipt = compiler.execute(input_request)
    assert receipt.wrote and not result.issue_codes
    admission = next(
        item for item in result.plan.source_admissions if item.kind == "quote"
    )
    assert admission.provider_id == SOURCE
    assert admission.quote_selection.security_id == value.expected_identity.security_id
    source = next(
        item for item in result.plan.public_sources if item.source_id == SOURCE
    )
    query = parse_qs(urlsplit(source.uri).query)
    assert query["period1"] == [str(int(admission.quote_selection.as_of.timestamp()))]
    assert query["interval"] == ["1d"]
    assert result == compiler.execute(input_request)[0]
    assert not compiler.execute(input_request)[1].wrote
    assert calls == (value.state.provider_calls, value.state.parser_calls)


def request():
    return PublicSourceAcquisitionRequestV1(
        source_id=SOURCE,
        uri=URI,
        source_profile=PROFILE,
        terms_reference=TERMS,
        valuation_timestamp=CAPTURE + timedelta(hours=1),
    )


def adapter(tmp_path, monkeypatch, *, use_policy, payload=None):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return CAPTURE

    monkeypatch.setattr("fundamental_service.public_source.datetime", Clock)
    calls = []

    class Response(FakeResponse):
        def read(self, size=-1):
            return self._payload if size == -1 else self._payload[:size]

    def opener(http_request, **kwargs):
        calls.append(http_request)
        if http_request.full_url == TERMS:
            return Response(TERMS_BYTES, "text/plain")
        return Response(
            raw_response() if payload is None else payload, "application/json"
        )

    value = quote_preparation_source_adapter(
        user_agent="fixture test@example.com",
        policy=use_policy,
        api_key_file=tmp_path / "this-credential-file-does-not-exist",
        quote_opener=opener,
        public_opener=opener,
    )
    return value, calls


def test_configured_capture_needs_no_key_and_reuses_full_admission_without_writes(
    tmp_path, monkeypatch
):
    source_policy = policy()
    provider, calls = adapter(tmp_path, monkeypatch, use_policy=source_policy)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    acquired = acquisition(tmp_path / "capture", provider, artifacts=artifacts)
    source_request = request()
    terms_request = source_request.model_copy(
        update={
            "source_id": YAHOO_TERMS_SOURCE,
            "uri": TERMS,
            "source_profile": "captured-terms-v1",
        }
    )
    requests = (source_request, terms_request)
    captures = tuple(
        acquired.read(acquired.execute(item).artifact.artifact_id) for item in requests
    )
    owner = PublicSourceAdmission(
        acquisitions=acquired,
        artifacts=artifacts,
        policy=source_policy,
        quote_providers=default_quote_providers(),
    )
    admission_request = PublicSourceAdmissionRequestV1(
        kind="quote",
        provider_id=SOURCE,
        metric_id="common_share.price",
        valuation_at=source_request.valuation_timestamp,
        policy_version=source_policy.policy_version,
        policy_digest=source_policy.digest,
        source_request_digests=(source_request.digest,),
        terms_request_digests=(terms_request.digest,),
        quote_selection=PublicQuoteSelectionV1(
            issuer_id="0000724910",
            security_id="NVEC",
            as_of=datetime.fromisoformat("2026-11-13T05:00:00+00:00"),
        ),
    )
    result, publication = owner.execute(admission_request, captures)
    assert publication.wrote and not result.issue_codes
    assert result.admission.status == "admitted"
    assert all(call.get_header("Authorization") is None for call in calls)
    assert acquired.retained_source(captures[0]).content == raw_response()
    before = inventory(tmp_path)
    for item in requests:
        assert not acquired.execute(item).wrote
    repeat, receipt = owner.execute(admission_request, captures)
    assert repeat == result and not receipt.wrote
    assert inventory(tmp_path) == before
    assert len(calls) == 2


@pytest.mark.parametrize(
    "mode,code",
    [
        ("missing", "SOURCE_USE_POLICY_MISSING"),
        ("ambiguous", "SOURCE_USE_POLICY_AMBIGUOUS"),
        ("wrong-purpose", "SOURCE_USE_PURPOSE_UNSUPPORTED"),
        ("oversized", "QUOTE_SOURCE_TOO_LARGE"),
    ],
)
def test_source_use_is_required_before_io_and_response_size_is_bounded(
    tmp_path, monkeypatch, mode, code
):
    use_policy = policy()
    if mode == "missing":
        use_policy = None
    elif mode == "ambiguous":
        use_policy = use_policy.model_copy(
            update={
                "rules": (
                    *use_policy.rules,
                    use_policy.rules[0].model_copy(
                        update={"rule_id": "synthetic-yahoo-grant-2"}
                    ),
                )
            }
        )
    elif mode == "wrong-purpose":
        use_policy = use_policy.model_copy(
            update={
                "rules": (
                    use_policy.rules[0].model_copy(
                        update={"permitted_uses": ("raw_data_redistribution",)}
                    ),
                )
            }
        )
    provider, calls = adapter(
        tmp_path,
        monkeypatch,
        use_policy=use_policy,
        payload=b"x" * (1024 * 1024 + 1),
    )
    acquired = acquisition(tmp_path, provider)
    result = acquired.read(acquired.execute(request()).artifact.artifact_id)
    assert result.status == "failed" and result.source is None
    assert result.issue_codes == (code,)
    assert len(calls) == (1 if mode == "oversized" else 0)
