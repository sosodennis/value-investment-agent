"""Exact, versioned content boundaries for trusted source-use requirements."""

from hashlib import sha256
from html.parser import HTMLParser
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HtmlTermsScopeV1(BaseModel):
    """Select one complete element, including its markup, links and restrictions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol: Literal["exact-html-element-v1"] = "exact-html-element-v1"
    tag: Literal["article", "main", "section", "div"]
    attribute: Literal["id", "about"]
    value: str = Field(min_length=1, max_length=1024)


class TermsContentError(ValueError):
    pass


_INERT_HTML_ELEMENTS = {
    "iframe",
    "math",
    "noembed",
    "noframes",
    "noscript",
    "plaintext",
    "script",
    "style",
    "svg",
    "template",
    "textarea",
    "title",
    "xmp",
}


class _ElementBoundary(HTMLParser):
    def __init__(self, text: str, scope: HtmlTermsScopeV1) -> None:
        super().__init__(convert_charrefs=False)
        self._text = text
        self._scope = scope
        self._line_offsets = [0]
        self._line_offsets.extend(
            index + 1 for index, char in enumerate(text) if char == "\n"
        )
        self._depth = 0
        self._start: int | None = None
        self._end: int | None = None
        self._matches = 0
        self._inactive: list[str] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._line_offsets[line - 1] + column

    def _matches_scope(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        if tag != self._scope.tag:
            return False
        values = [value for key, value in attrs if key == self._scope.attribute]
        if len(values) > 1:
            raise TermsContentError("terms selector attribute is duplicated")
        return values == [self._scope.value]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _INERT_HTML_ELEMENTS:
            self._inactive.append(tag)
        if self._matches_scope(tag, attrs):
            if self._inactive:
                raise TermsContentError("terms element is inside inactive content")
            self._matches += 1
            if self._matches != 1:
                raise TermsContentError("terms content selection is ambiguous")
            self._start = self._offset()
            self._depth = 1
        elif self._depth and tag == self._scope.tag:
            self._depth += 1
            if self._depth > 128:
                raise TermsContentError("terms element nesting exceeds its limit")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._matches_scope(tag, attrs):
            raise TermsContentError("terms content element cannot be self-closing")

    def handle_endtag(self, tag: str) -> None:
        if self._inactive and tag == self._inactive[-1]:
            self._inactive.pop()
        if not self._depth or tag != self._scope.tag:
            return
        self._depth -= 1
        if not self._depth:
            offset = self._offset()
            closing = re.match(
                rf"</{re.escape(tag)}[ \t\n\r\f]*>",
                self._text[offset:],
                flags=re.IGNORECASE,
            )
            if closing is None:
                raise TermsContentError("terms content has a malformed closing tag")
            self._end = offset + closing.end()

    def selected_bytes(self) -> bytes:
        if (
            self._matches != 1
            or self._depth
            or self._start is None
            or self._end is None
        ):
            raise TermsContentError("terms content requires one complete element")
        return self._text[self._start : self._end].encode("utf-8")


def terms_content_digest(content: bytes, scope: HtmlTermsScopeV1 | None) -> str:
    """Hash exact original bytes, or the exact complete trusted HTML scope."""
    if scope is None:
        return sha256(content).hexdigest()
    if not content or len(content) > 2 * 1024 * 1024:
        raise TermsContentError("scoped terms document is empty or exceeds its limit")
    try:
        text = content.decode("utf-8")
    except UnicodeError as error:
        raise TermsContentError("scoped terms require UTF-8 original bytes") from error
    parser = _ElementBoundary(text, scope)
    parser.feed(text)
    parser.close()
    return sha256(parser.selected_bytes()).hexdigest()
