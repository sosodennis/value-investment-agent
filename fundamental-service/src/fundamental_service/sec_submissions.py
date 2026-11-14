"""SEC submissions transport schemas shared by discovery and acquisition."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class SecRecentFilingsV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    accessionNumber: list[str]
    filingDate: list[str]
    acceptanceDateTime: list[str | None]
    form: list[str]
    primaryDocument: list[str]
    isXBRL: list[int | str]
    isInlineXBRL: list[int | str] | None = None
    reportDate: list[str] | None = None

    def require_aligned_columns(self) -> None:
        columns = (
            self.accessionNumber,
            self.filingDate,
            self.acceptanceDateTime,
            self.form,
            self.primaryDocument,
            self.isXBRL,
            self.isInlineXBRL,
            self.reportDate,
        )
        if len({len(column) for column in columns if column is not None}) != 1:
            raise ValueError("SEC submissions columns have inconsistent lengths")


class SecSubmissionHistoryReferenceV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(pattern=r"^CIK\d{10}-submissions-\d{3}\.json$")
    filingCount: int = Field(ge=1)
    filingFrom: date
    filingTo: date


class SecFilingsV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    recent: SecRecentFilingsV1
    files: list[SecSubmissionHistoryReferenceV1] | None = None


class SecSubmissionsV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    cik: int | str
    tickers: list[str] = Field(default_factory=list)
    filings: SecFilingsV1
