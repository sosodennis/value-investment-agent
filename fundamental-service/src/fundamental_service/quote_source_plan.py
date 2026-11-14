"""Compile a deployment quote template from verified original identity."""

from datetime import UTC, datetime, time, timedelta
from string import Formatter
from typing import Literal
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from .contracts import IdentityV1, StrictModel
from .public_acquisition import PublicSourceAcquisitionRequestV1
from .public_admission import PublicQuoteSelectionV1

_NEW_YORK = ZoneInfo("America/New_York")


class AutomaticDailyQuoteRequestTemplateV1(StrictModel):
    protocol: Literal["automatic-us-common-previous-weekday-quote-template-v1"] = (
        "automatic-us-common-previous-weekday-quote-template-v1"
    )
    source_id: str = Field(min_length=1)
    uri_template: str = Field(min_length=1)
    source_profile: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)

    @model_validator(mode="after")
    def dated_security_uri(self) -> "AutomaticDailyQuoteRequestTemplateV1":
        try:
            fields = tuple(Formatter().parse(self.uri_template))
        except ValueError as error:
            raise ValueError("quote source URI template is malformed") from error
        if {field for _, field, _, _ in fields if field is not None} != {
            "security_id",
            "observation_date",
        } or any(spec or conversion for _, _, spec, conversion in fields):
            raise ValueError("quote template requires only security and date fields")
        example = self.uri_template.format(
            security_id="EXAMPLE", observation_date="2000-01-03"
        )
        uri = urlsplit(example)
        if (
            uri.scheme != "https"
            or not uri.hostname
            or uri.username is not None
            or uri.password is not None
            or uri.fragment
        ):
            raise ValueError("quote source URI template must resolve to HTTPS")
        return self

    def render(
        self, *, identity: IdentityV1, valuation_at: datetime
    ) -> tuple[PublicSourceAcquisitionRequestV1, PublicQuoteSelectionV1]:
        if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
            raise ValueError("quote source template requires a zoned valuation time")
        if identity.currency != "USD":
            raise ValueError("US daily quote template requires a USD security")
        valuation_at = valuation_at.astimezone(UTC)
        day = valuation_at.astimezone(_NEW_YORK).date() - timedelta(days=1)
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        selection = PublicQuoteSelectionV1(
            issuer_id=identity.issuer_id,
            security_id=identity.security_id,
            as_of=datetime.combine(day, time.min, _NEW_YORK).astimezone(UTC),
        )
        request = PublicSourceAcquisitionRequestV1(
            source_id=self.source_id,
            uri=self.uri_template.format(
                security_id=quote(identity.security_id, safe=""),
                observation_date=day.isoformat(),
            ),
            source_profile=self.source_profile,
            terms_reference=self.terms_reference,
            valuation_timestamp=valuation_at,
        )
        return request, selection
