import hashlib

import pytest

from fundamental_service.terms_content import (
    HtmlTermsScopeV1,
    TermsContentError,
    terms_content_digest,
)


SCOPE = HtmlTermsScopeV1(tag="article", attribute="about", value="/terms")
ARTICLE = b'<article about="/terms"><p>Original terms &amp; links.</p></article>'


def test_extracts_exact_utf8_bytes_with_lf_crlf_and_lone_carriage_returns():
    for prefix in ("", "\r", "\r\n", "\n", "繁體中文\r\n"):
        raw = prefix.encode() + ARTICLE + b"\r\n<footer>new assets</footer>"
        assert terms_content_digest(raw, SCOPE) == hashlib.sha256(ARTICLE).hexdigest()


def test_nested_nonmatching_elements_are_part_of_the_complete_scope():
    scope = HtmlTermsScopeV1(tag="div", attribute="id", value="terms")
    raw = b'<div id="terms"><div>Every restriction</div>and trailing text</div>'
    assert (
        terms_content_digest(raw + b"new shell", scope)
        == hashlib.sha256(raw).hexdigest()
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff" + ARTICLE,
        b"x" * (2 * 1024 * 1024 + 1),
        b"<!--" + ARTICLE + b"-->",
        b"<script>" + ARTICLE + b"</script>",
        b"<iframe>" + ARTICLE + b"</iframe>",
        b'<article about="/terms"/>',
        b'<article about="/terms" about="/terms">text</article>',
        ARTICLE.replace(b'about="/terms"', b'about="/other"'),
        ARTICLE + ARTICLE,
        ARTICLE.replace(b"</article>", b""),
        ARTICLE.replace(b"</article>", b"<article>not complete</article>"),
        ARTICLE.replace(b"</article>", b'</article note=">">'),
        b"<noscript>" + ARTICLE + b"</noscript>",
        b"<svg>" + ARTICLE + b"</svg>",
    ],
)
def test_ambiguous_incomplete_inert_or_unbounded_content_is_refused(raw):
    with pytest.raises(TermsContentError):
        terms_content_digest(raw, SCOPE)


def test_whole_document_hash_has_no_html_interpretation_or_new_limits():
    raw = b"\xffnot html"
    assert terms_content_digest(raw, None) == hashlib.sha256(raw).hexdigest()
