"""Synthetic source grants exercise acquisition through official composition."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from fundamental_service.contracts import SourceRole, CallerApprovalEnvelopeV1
from fundamental_service.data_releases import DataReleaseManifestV1
from fundamental_service.public_acquisition import PublicSourceAcquisitionRequestV1
from fundamental_service.public_admission import (
    PublicQuoteSelectionV1,
    PublicSourceAdmission,
    PublicSourceAdmissionRequestV1,
)
from fundamental_service.quote_admission import QUOTE_ADMISSION_ROLE, QUOTE_TERMS_ROLE
from fundamental_service.quote_capture import (
    quote_preparation_source_adapter,
    TWELVE_TERMS_SOURCE,
)
from fundamental_service.quote_sources import default_quote_providers
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import CapturedSource, SnapshotError
from fundamental_service.source_admission import (
    SourceUsePolicyV1,
    SourceUseRuleV1,
    TermsRequirementV1,
)
from fundamental_service.source_capture import SourceCaptureRequest
from fundamental_service.twelve_quote_source import (
    TWELVE_CLOSE_SOURCE,
    TWELVE_CLOSE_PROFILE,
    TWELVE_TERMS,
)
from test_public_acquisition import acquisition, inventory
from test_public_source import FakeResponse
from test_preparation_runner import _fixture, _run, _reader, _runner, VALUATION_TIME
from test_twelve_quote_source import _response, _query
from test_equity_award_evidence import _with_alternative_quote


def quote_fixture(tmp_path, *, baseline=None):
    baseline = baseline or _fixture(tmp_path / "baseline")
    identity = baseline.snapshot.identity
    captured = VALUATION_TIME - timedelta(hours=1)
    day = date(2026, 2, 27)
    uri = "https://api.twelvedata.com/time_series?" + urlencode(
        {**_query(), "symbol": identity.security_id, "date": day.isoformat()}
    )
    response = _response()
    response["meta"]["symbol"] = identity.security_id
    response["values"][0].update(datetime=day.isoformat(), close="10")
    raw = canonical_bytes(response)
    terms = b"Synthetic fixture rights only; no actual provider entitlement."
    rule = SourceUseRuleV1(
        rule_id="synthetic-quote-preparation",
        provider_id=TWELVE_CLOSE_SOURCE,
        metric_id="common_share.price",
        population="common-share",
        source_id=TWELVE_CLOSE_SOURCE,
        source_version=TWELVE_CLOSE_PROFILE,
        terms_reference=TWELVE_TERMS,
        permitted_uses=("valuation_preparation",),
        terms=(
            TermsRequirementV1(
                uri=TWELVE_TERMS, content_sha256=sha256(terms).hexdigest()
            ),
        ),
        required_notices=("Synthetic quote permission only",),
        basis="Test-only bytes",
    )
    base = baseline.application.source_use_policy
    policy = SourceUsePolicyV1(
        policy_version="synthetic-quote-preparation-v1",
        rules=tuple(
            sorted(
                (
                    *(r for r in base.rules if r.provider_id != TWELVE_CLOSE_SOURCE),
                    rule,
                ),
                key=lambda r: r.rule_id,
            )
        ),
    )
    requests = tuple(
        PublicSourceAcquisitionRequestV1(
            source_id=source_id,
            uri=source_uri,
            source_profile=profile,
            terms_reference=TWELVE_TERMS,
            valuation_timestamp=VALUATION_TIME,
        )
        for source_id, source_uri, profile in (
            (TWELVE_CLOSE_SOURCE, uri, TWELVE_CLOSE_PROFILE),
            (TWELVE_TERMS_SOURCE, TWELVE_TERMS, "captured-terms-v1"),
        )
    )

    class Capture:
        def __init__(self):
            self.calls = []
            self.sources = {
                item.uri: CapturedSource(
                    source_id=item.source_id,
                    uri=item.uri,
                    role=SourceRole.REFERENCE,
                    content=raw if item.source_id == TWELVE_CLOSE_SOURCE else terms,
                    media_type="application/json"
                    if item.source_id == TWELVE_CLOSE_SOURCE
                    else "text/plain",
                    http_status=200,
                    available_at=captured,
                    captured_at=captured,
                )
                for item in requests
            }

        def validate_capture(self, source_id, uri):
            return SourceCaptureRequest(source_id, uri, TWELVE_TERMS)

        def capture(self, source_id, uri):
            self.calls.append(uri)
            return self.sources[uri]

    capture = Capture()
    acquired = acquisition(tmp_path / "public", capture, artifacts=baseline.artifacts)
    request = PublicSourceAdmissionRequestV1(
        kind="quote",
        provider_id=TWELVE_CLOSE_SOURCE,
        metric_id="common_share.price",
        valuation_at=VALUATION_TIME,
        policy_version=policy.policy_version,
        policy_digest=policy.digest,
        source_request_digests=(requests[0].digest,),
        terms_request_digests=(requests[1].digest,),
        quote_selection=PublicQuoteSelectionV1(
            issuer_id=identity.issuer_id,
            security_id=identity.security_id,
            as_of=datetime(2026, 2, 27, 5, tzinfo=UTC),
        ),
    )

    def service(*, use_policy=policy, providers=None):
        return PublicSourceAdmission(
            acquisitions=acquired,
            artifacts=baseline.artifacts,
            policy=use_policy,
            quote_providers=default_quote_providers()
            if providers is None
            else providers,
        )

    def captures():
        return tuple(
            acquired.read(acquired.execute(item).artifact.artifact_id)
            for item in requests
        )

    return SimpleNamespace(
        baseline=baseline,
        capture=capture,
        acquisition=acquired,
        request=request,
        requests=requests,
        policy=policy,
        service=service,
        captures=captures,
        raw=raw,
        terms=terms,
    )


def test_quote_preparation_reuses_originals_and_exact_release_lineage(tmp_path):
    fixture = quote_fixture(tmp_path)
    captures = fixture.captures()
    result, first = fixture.service().execute(fixture.request, captures)
    assert result.admission.status == "admitted" and not result.issue_codes
    assert len(result.release_refs) == 3
    assert {ref.role for ref in result.release_refs} == {
        QUOTE_ADMISSION_ROLE,
        QUOTE_TERMS_ROLE,
        "equity-dilution-quote-source-v1",
    }
    assert result.admission.request.quote.price == 10
    before = inventory(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        repeats = list(
            pool.map(
                lambda _: fixture.service().execute(
                    fixture.request, fixture.captures()
                ),
                range(2),
            )
        )
    assert all(
        row == result and receipt.artifact == first.artifact and not receipt.wrote
        for row, receipt in repeats
    )
    assert len(fixture.capture.calls) == 2 and before == inventory(tmp_path)


@pytest.mark.parametrize(
    "failure,code",
    [
        ("raw", "SOURCE_REPRODUCTION_FAILED"),
        ("terms", "SOURCE_USE_TERMS_CHANGED"),
        ("late", "SOURCE_NOT_AVAILABLE_AT_VALUATION"),
        ("policy", "SOURCE_ADMISSION_POLICY_MISMATCH"),
        ("permission", "SOURCE_USE_POLICY_MISSING"),
        ("provider", "SOURCE_ADMISSION_PROVIDER_UNAVAILABLE"),
        ("as_of", "DILUTION_QUOTE_SOURCE_VALUE_MISMATCH"),
    ],
)
def test_quote_preparation_retains_refusals_and_originals(tmp_path, failure, code):
    fixture = quote_fixture(tmp_path)
    request = fixture.request
    policy = fixture.policy
    if failure in {"raw", "terms", "late"}:
        uri = fixture.requests[1 if failure == "terms" else 0].uri
        original = fixture.capture.sources[uri]
        fixture.capture.sources[uri] = replace(
            original,
            **(
                {"content": b"malformed or changed"}
                if failure != "late"
                else {
                    "available_at": VALUATION_TIME + timedelta(seconds=1),
                    "captured_at": VALUATION_TIME + timedelta(seconds=1),
                }
            ),
        )
    if failure in {"policy", "permission"}:
        policy = SourceUsePolicyV1(policy_version="no-grant", rules=())
        if failure == "permission":
            request = request.model_copy(
                update={
                    "policy_version": policy.policy_version,
                    "policy_digest": policy.digest,
                }
            )
    if failure == "as_of":
        request = request.model_copy(
            update={
                "quote_selection": request.quote_selection.model_copy(
                    update={"as_of": request.quote_selection.as_of + timedelta(hours=1)}
                )
            }
        )
    captures = fixture.captures()
    service = fixture.service(
        use_policy=policy, providers=() if failure == "provider" else None
    )
    result, first = service.execute(request, captures)
    assert code in result.issue_codes and not result.release_refs
    assert len(result.source_refs) == len(result.terms_refs) == 1
    before = inventory(tmp_path)
    repeated, receipt = service.execute(request, captures)
    assert (
        repeated == result and first.artifact == receipt.artifact and not receipt.wrote
    )
    assert inventory(tmp_path) == before


def test_quote_admission_flows_through_runner_composer_and_exact_approval(tmp_path):
    fixture = quote_fixture(tmp_path)
    baseline = fixture.baseline
    result, _ = fixture.service().execute(fixture.request, fixture.captures())
    _with_alternative_quote(
        baseline, quote=result.admission.request.quote, raw=fixture.raw
    )
    payload = baseline.manifest.model_dump(exclude={"manifest_digest"})
    payload["artifact_refs"] = (
        tuple(
            ref
            for ref in baseline.manifest.artifact_refs
            if ref.role
            not in {
                QUOTE_ADMISSION_ROLE,
                QUOTE_TERMS_ROLE,
                "equity-dilution-quote-source-v1",
            }
        )
        + result.release_refs
    )
    baseline.manifest = DataReleaseManifestV1(
        **payload, manifest_digest=sha256_digest(payload)
    )
    baseline.state.active = baseline.active.model_copy(
        update={
            "active": baseline.active.active.model_copy(
                update={"manifest_digest": baseline.manifest.manifest_digest}
            ),
            "manifest": baseline.manifest,
        }
    )
    baseline.application = replace(
        baseline.application, source_use_policy=fixture.policy
    )
    baseline.metadata.get_data_release_manifest = (
        lambda digest: baseline.manifest
        if digest == baseline.manifest.manifest_digest
        else None
    )
    plan = type(baseline.plan).model_validate(
        {
            **baseline.plan.model_dump(),
            "public_sources": fixture.requests,
            "source_admissions": (fixture.request,),
        }
    )
    runner = _runner(
        baseline,
        public_acquisition=fixture.acquisition,
        public_admission=fixture.service(),
    )
    waiting = _reader(baseline, _run(runner, plan))
    assert waiting.status == "approval_required" and waiting.calculation is None
    assert waiting.preparation.equity_dilution.incremental_shares == 10
    assert waiting.preparation.quality_status.value == "provisional"
    approval = CallerApprovalEnvelopeV1(
        caller_id="operator",
        decision="approved",
        input_digest=waiting.preparation.input.input_digest,
        decided_at=VALUATION_TIME,
    )
    first = _run(runner, plan, approval=approval)
    report = _reader(baseline, first)
    assert report.status == "calculated" and report.calculation is not None
    before = inventory(tmp_path)
    repeat = _run(runner, plan, approval=approval)
    assert (
        not repeat.wrote
        and repeat.artifact == first.artifact
        and inventory(tmp_path) == before
    )
    assert len(fixture.capture.calls) == 2
    bad = {
        **plan.model_dump(),
        "source_admissions": (
            {
                **fixture.request.model_dump(),
                "quote_selection": {
                    **fixture.request.quote_selection.model_dump(),
                    "security_id": "OTHER",
                },
            },
        ),
    }
    with pytest.raises(ValueError, match="identity"):
        type(plan).model_validate(bad)


def test_quote_capture_uses_header_only_and_retains_malformed_original(tmp_path):
    fixture = quote_fixture(tmp_path / "fixture")
    key_file = tmp_path / "key"
    key_file.write_text("synthetic-key-not-a-real-credential")
    calls = []

    class Response(FakeResponse):
        def read(self, size):
            return self._payload[:size]

    def opener(request, **kwargs):
        calls.append(request)
        return Response(b"malformed upstream bytes", "application/json")

    adapter = quote_preparation_source_adapter(
        user_agent="test test@example.com",
        policy=fixture.policy,
        api_key_file=key_file,
        quote_opener=opener,
    )
    acquired = acquisition(tmp_path / "capture", adapter)
    first = acquired.execute(fixture.requests[0])
    outcome = acquired.read(first.artifact.artifact_id)
    assert outcome.status == "captured"
    assert acquired.retained_source(outcome).content == b"malformed upstream bytes"
    assert calls[0].get_header("Authorization") == "apikey " + key_file.read_text()
    assert key_file.read_text() not in calls[0].full_url
    assert key_file.read_bytes() not in canonical_bytes(outcome)
    key_file.unlink()
    repeat = acquired.execute(fixture.requests[0])
    assert not repeat.wrote and repeat.artifact == first.artifact and len(calls) == 1


@pytest.mark.parametrize(
    "failure,code",
    [
        ("permission", "SOURCE_USE_POLICY_MISSING"),
        ("key", "QUOTE_SOURCE_CREDENTIAL_UNAVAILABLE"),
        ("large", "QUOTE_SOURCE_TOO_LARGE"),
        ("echo", "QUOTE_SOURCE_CREDENTIAL_ECHO_REFUSED"),
    ],
)
def test_quote_capture_refuses_before_unauthorized_io_or_secret_persistence(
    tmp_path, failure, code
):
    fixture = quote_fixture(tmp_path / "fixture")
    key_file = tmp_path / "key"
    key_file.write_text("synthetic-key-not-a-real-credential")
    calls = []

    class Response(FakeResponse):
        def read(self, size):
            return self._payload[:size]

    def opener(request, **kwargs):
        calls.append(True)
        return Response(
            b"x" * (1024 * 1024 + 1) if failure == "large" else key_file.read_bytes()
        )

    adapter = quote_preparation_source_adapter(
        user_agent="test test@example.com",
        policy=None if failure == "permission" else fixture.policy,
        api_key_file=None if failure == "key" else key_file,
        quote_opener=opener,
    )
    acquired = acquisition(tmp_path / "capture", adapter)
    first = acquired.execute(fixture.requests[0])
    outcome = acquired.read(first.artifact.artifact_id)
    assert (
        outcome.status == "failed"
        and outcome.issue_codes == (code,)
        and outcome.source is None
    )
    assert bool(calls) == (failure in {"large", "echo"})
    assert not list((tmp_path / "capture" / "content").rglob("*.json"))


def test_quote_capture_never_follows_authenticated_redirect():
    from fundamental_service.quote_capture import _NoQuoteRedirect
    from urllib.request import Request
    from email.message import Message

    request = Request("https://api.twelvedata.com/time_series")
    request.add_header("Authorization", "apikey synthetic-key")
    with pytest.raises(SnapshotError) as error:
        _NoQuoteRedirect().redirect_request(
            request, None, 302, "Found", Message(), "https://example.test/stolen"
        )
    assert error.value.code == "QUOTE_SOURCE_REDIRECT_REFUSED"


def test_current_quote_selection_freezes_actual_capture_without_backdating(tmp_path):
    from fundamental_service.current_preparation import (
        CurrentSourcePreparation,
        CurrentSourcePreparationRequestV1,
    )
    from test_public_acquisition import file_lock

    fixture = quote_fixture(tmp_path)
    requested = VALUATION_TIME - timedelta(seconds=2)
    requests = tuple(
        item.model_copy(update={"valuation_timestamp": requested})
        for item in fixture.requests
    )
    admission = fixture.request.model_copy(
        update={
            "valuation_at": requested,
            "source_request_digests": (requests[0].digest,),
            "terms_request_digests": (requests[1].digest,),
        }
    )
    template = type(fixture.baseline.plan).model_validate(
        {
            **fixture.baseline.plan.model_dump(),
            "ingestions": tuple(
                {**item.model_dump(), "valuation_timestamp": requested}
                for item in fixture.baseline.plan.ingestions
            ),
            "public_sources": requests,
            "source_admissions": (admission,),
        }
    )
    for uri, source in fixture.capture.sources.items():
        fixture.capture.sources[uri] = replace(
            source, available_at=VALUATION_TIME, captured_at=VALUATION_TIME
        )
    selector = CurrentSourcePreparation(
        acquisitions=fixture.acquisition,
        artifacts=fixture.baseline.artifacts,
        selection_lock=lambda key: file_lock(tmp_path / "selection-locks", key),
        clock=lambda: VALUATION_TIME + timedelta(seconds=1),
    )
    request = CurrentSourcePreparationRequestV1(template=template)
    selected, first = selector.execute(
        request, deadline_at=VALUATION_TIME + timedelta(minutes=1)
    )
    assert selected.plan.ingestions[0].valuation_timestamp == VALUATION_TIME
    prepared = selected.plan.source_admissions[0]
    assert (
        prepared.valuation_at == VALUATION_TIME
        and prepared.quote_selection == admission.quote_selection
    )
    result, _ = fixture.service().execute(prepared, selected.captures)
    assert (
        result.admission.status == "admitted"
        and result.admission.request.quote.available_at == VALUATION_TIME
    )
    before = inventory(tmp_path)
    repeated, receipt = selector.execute(
        request, deadline_at=VALUATION_TIME + timedelta(minutes=1)
    )
    assert (
        repeated == selected
        and receipt.artifact == first.artifact
        and not receipt.wrote
    )
    assert len(fixture.capture.calls) == 2 and inventory(tmp_path) == before


def test_configured_quote_provider_can_change_without_preparation_branching(tmp_path):
    from quote_provider_fixtures import SyntheticQuoteProvider

    fixture = quote_fixture(tmp_path)
    source = fixture.requests[0].model_copy(
        update={
            "source_id": "synthetic-quote-vendor",
            "source_profile": "synthetic-v1",
            "terms_reference": "synthetic-test-only",
        }
    )
    fixture.capture.sources[source.uri] = replace(
        fixture.capture.sources[source.uri],
        source_id=source.source_id,
        content=canonical_bytes({"price": "12", "currency": "USD"}),
    )

    class Capture:
        def validate_capture(self, source_id, uri):
            return SourceCaptureRequest(
                source_id,
                uri,
                source.terms_reference if uri == source.uri else TWELVE_TERMS,
            )

        def capture(self, source_id, uri):
            return fixture.capture.capture(source_id, uri)

    acquired = acquisition(
        tmp_path / "alternative", Capture(), artifacts=fixture.baseline.artifacts
    )
    policy = SourceUsePolicyV1(
        policy_version="alternative-test-only",
        rules=(
            next(
                rule
                for rule in fixture.policy.rules
                if rule.rule_id == "synthetic-quote-preparation"
            ).model_copy(
                update={
                    "provider_id": source.source_id,
                    "source_id": source.source_id,
                    "source_version": source.source_profile,
                    "terms_reference": source.terms_reference,
                }
            ),
        ),
    )
    request = fixture.request.model_copy(
        update={
            "provider_id": source.source_id,
            "source_request_digests": (source.digest,),
            "policy_version": policy.policy_version,
            "policy_digest": policy.digest,
        }
    )
    service = PublicSourceAdmission(
        acquisitions=acquired,
        artifacts=fixture.baseline.artifacts,
        policy=policy,
        quote_providers=(SyntheticQuoteProvider(),),
    )
    captures = tuple(
        acquired.read(acquired.execute(item).artifact.artifact_id)
        for item in (source, fixture.requests[1])
    )
    result, _ = service.execute(request, captures)
    assert (
        result.admission.status == "admitted"
        and result.admission.request.quote.price == 12
    )


def test_quote_admission_resumes_after_interrupted_publication(tmp_path, monkeypatch):
    fixture = quote_fixture(tmp_path)
    captures = fixture.captures()
    writer = fixture.baseline.artifacts.put_with_receipt

    def interrupted(artifact_id, *args, **kwargs):
        receipt = writer(artifact_id, *args, **kwargs)
        if artifact_id.startswith("quote-admission:"):
            raise RuntimeError("interrupted after durable quote decision")
        return receipt

    monkeypatch.setattr(fixture.baseline.artifacts, "put_with_receipt", interrupted)
    with pytest.raises(RuntimeError, match="durable quote"):
        fixture.service().execute(fixture.request, captures)
    monkeypatch.setattr(fixture.baseline.artifacts, "put_with_receipt", writer)
    first, receipt = fixture.service().execute(fixture.request, captures)
    before = inventory(tmp_path)
    repeated, again = fixture.service().execute(fixture.request, fixture.captures())
    assert repeated == first and receipt.wrote and not again.wrote
    assert len(fixture.capture.calls) == 2 and inventory(tmp_path) == before


def test_configuration_refusal_does_not_permanently_poison_acquisition(tmp_path):
    fixture = quote_fixture(tmp_path / "fixture")
    key_file = tmp_path / "key"
    key_file.write_text("synthetic-key-not-a-real-credential")

    class Response(FakeResponse):
        def read(self, size):
            return self._payload[:size]

    calls = []

    def opener(*args, **kwargs):
        calls.append(True)
        return Response(fixture.raw, "application/json")

    def configured(policy):
        adapter = quote_preparation_source_adapter(
            user_agent="test test@example.com",
            policy=policy,
            api_key_file=key_file,
            quote_opener=opener,
        )
        return acquisition(tmp_path / "capture", adapter)

    denied = configured(None)
    refusal = denied.read(denied.execute(fixture.requests[0]).artifact.artifact_id)
    assert refusal.retryable and not calls
    allowed = configured(fixture.policy)
    first = allowed.execute(fixture.requests[0])
    assert (
        allowed.read(first.artifact.artifact_id).status == "captured"
        and len(calls) == 1
    )
    before = inventory(tmp_path)
    assert (
        not allowed.execute(fixture.requests[0]).wrote and inventory(tmp_path) == before
    )
    assert denied.read(refusal.artifact_id) == refusal
