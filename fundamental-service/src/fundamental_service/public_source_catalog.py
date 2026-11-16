"""Composition-owned public source registrations and capture profiles."""

from urllib.parse import urlsplit

from .contracts import SourceRole
from .damodaran_source import damodaran_reference_profile
from .bea_source import BEA_CURRENT_GDP_URI
from .snapshots import SnapshotError
from .sofr_source import (
    NEW_YORK_FED_SOFR_PROFILE,
    NewYorkFedSofrVintageProvider,
    sofr_request_date,
)
from .source_capture import (
    ProvidedAvailabilityCaptureProfile,
    PublicSourceCaptureProfilePort,
    PublicSourceRegistration,
    PublicSourceSpec,
    ReproducedMacroCaptureProfile,
    RetainedAvailabilityCaptureProfile,
)
from .treasury_source import (
    ALFRED_TREASURY_PROFILE,
    TREASURY_PROFILE,
    TREASURY_SERIES,
    AlfredTreasuryVintageProvider,
    TreasuryParYieldVintageProvider,
    alfred_treasury_request,
    treasury_request_year,
)

PUBLIC_SOURCE_SPECS: tuple[PublicSourceSpec, ...] = (
    PublicSourceSpec(
        "treasury-yields",
        SourceRole.MACRO,
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/",
        "https://fiscaldata.treasury.gov/terms-of-use/",
    ),
    PublicSourceSpec(
        "fred-observations",
        SourceRole.MACRO,
        "https://fred.stlouisfed.org/graph/fredgraph.csv",
        "https://fred.stlouisfed.org/terms-of-use/",
        path_match="exact",
    ),
    PublicSourceSpec(
        "alfred-vintage",
        SourceRole.MACRO,
        "https://alfred.stlouisfed.org/graph/alfredgraph.csv",
        "https://fred.stlouisfed.org/terms-of-use/",
        path_match="exact",
    ),
    PublicSourceSpec(
        "bea-public-dataset",
        SourceRole.MACRO,
        "https://apps.bea.gov/",
        "https://apps.bea.gov/API/signup/",
    ),
    PublicSourceSpec(
        "bea-nipa-current",
        SourceRole.MACRO,
        BEA_CURRENT_GDP_URI,
        "https://www.bea.gov/help/guidelines-for-citing-bea",
        path_match="exact",
    ),
    PublicSourceSpec(
        "bea-gdp-release",
        SourceRole.MACRO,
        "https://www.bea.gov/news/",
        "https://www.bea.gov/help/guidelines-for-citing-bea",
    ),
    PublicSourceSpec(
        "bea-nipa-archive",
        SourceRole.MACRO,
        "https://apps.bea.gov/HistData/Files/Releases/GDP_and_PI/",
        "https://www.bea.gov/help/guidelines-for-citing-bea",
    ),
    PublicSourceSpec(
        "bls-public-api",
        SourceRole.MACRO,
        "https://api.bls.gov/publicAPI/",
        "https://www.bls.gov/developers/",
    ),
    PublicSourceSpec(
        "federal-reserve-h15",
        SourceRole.MACRO,
        "https://www.federalreserve.gov/datadownload/",
        "https://www.federalreserve.gov/data.htm",
    ),
    PublicSourceSpec(
        "new-york-fed-sofr",
        SourceRole.MACRO,
        "https://markets.newyorkfed.org/api/rates/secured/sofr/search.json",
        "https://www.newyorkfed.org/privacy/termsofuse",
        path_match="exact",
    ),
    PublicSourceSpec(
        "federal-reserve-policy",
        SourceRole.REFERENCE,
        "https://www.federalreserve.gov/newsevents/pressreleases/",
        "https://www.federalreserve.gov/disclaimer.htm",
    ),
    PublicSourceSpec(
        "damodaran-archive-index",
        SourceRole.REFERENCE,
        "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html",
        "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/",
    ),
    PublicSourceSpec(
        "fdic-bankfind",
        SourceRole.REFERENCE,
        "https://banks.data.fdic.gov/api/",
        "https://banks.data.fdic.gov/docs/",
    ),
    PublicSourceSpec(
        "ffiec-cdr",
        SourceRole.REFERENCE,
        "https://cdr.ffiec.gov/public/",
        "https://www.ffiec.gov/",
    ),
    PublicSourceSpec(
        "damodaran-reference",
        SourceRole.REFERENCE,
        "https://pages.stern.nyu.edu/~adamodar/pc/",
        "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/",
    ),
    # Post-cutover family sources.  Registration records the lawful public
    # boundary even while a family remains exploratory and cannot calculate.
    PublicSourceSpec(
        "naic-statutory-filings",
        SourceRole.REFERENCE,
        "https://content.naic.org/",
        "https://content.naic.org/insurance-topics/financial-data-repository",
    ),
    PublicSourceSpec(
        "nareit-definitions",
        SourceRole.REFERENCE,
        "https://www.reit.com/",
        "https://www.reit.com/terms-of-use",
    ),
    PublicSourceSpec(
        "ferc-public-data",
        SourceRole.REFERENCE,
        "https://www.ferc.gov/",
        "https://www.ferc.gov/terms-use",
    ),
    PublicSourceSpec(
        "state-utility-orders",
        SourceRole.REFERENCE,
        "https://www.naruc.org/",
        "https://www.naruc.org/about-naruc/",
    ),
    PublicSourceSpec(
        "eia-open-data",
        SourceRole.REFERENCE,
        "https://api.eia.gov/",
        "https://www.eia.gov/about/copyrights_reuse.php",
    ),
    PublicSourceSpec(
        "usgs-commodity-statistics",
        SourceRole.REFERENCE,
        "https://www.usgs.gov/centers/national-minerals-information-center/",
        "https://www.usgs.gov/information-policies",
    ),
    PublicSourceSpec(
        "usda-nass-quickstats",
        SourceRole.REFERENCE,
        "https://quickstats.nass.usda.gov/api/",
        "https://www.nass.usda.gov/About_NASS/",
    ),
    PublicSourceSpec(
        "fda-drugs",
        SourceRole.REFERENCE,
        "https://www.accessdata.fda.gov/",
        "https://www.fda.gov/about-fda/website-policies",
    ),
    PublicSourceSpec(
        "clinicaltrials-api",
        SourceRole.REFERENCE,
        "https://clinicaltrials.gov/data-api/api/",
        "https://clinicaltrials.gov/about-site/terms-conditions",
    ),
    PublicSourceSpec(
        "ifrs-taxonomy",
        SourceRole.TAXONOMY,
        "https://www.ifrs.org/issued-standards/ifrs-taxonomy/",
        "https://www.ifrs.org/legal/terms-and-conditions/",
    ),
    PublicSourceSpec(
        "damodaran-use-terms",
        SourceRole.REFERENCE,
        "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datahistory.html",
        "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datahistory.html",
        path_match="exact",
    ),
    PublicSourceSpec(
        "bea-citation-terms",
        SourceRole.REFERENCE,
        "https://www.bea.gov/help/guidelines-for-citing-bea",
        "https://www.bea.gov/help/guidelines-for-citing-bea",
        path_match="exact",
    ),
    PublicSourceSpec(
        "us-government-works-terms",
        SourceRole.REFERENCE,
        "https://www.govinfo.gov/content/pkg/USCODE-2024-title17/html/USCODE-2024-title17-chap1-sec105.htm",
        "https://www.govinfo.gov/content/pkg/USCODE-2024-title17/html/USCODE-2024-title17-chap1-sec105.htm",
        path_match="exact",
    ),
    PublicSourceSpec(
        "new-york-fed-use-terms",
        SourceRole.REFERENCE,
        "https://www.newyorkfed.org/privacy/termsofuse",
        "https://www.newyorkfed.org/privacy/termsofuse",
        path_match="exact",
    ),
)


def _bea_uri(uri: str) -> None:
    parsed = urlsplit(uri)
    if parsed.query or parsed.fragment:
        raise SnapshotError(
            "SOURCE_QUERY_INVALID", "BEA GDP requires canonical query-free source URIs"
        )


def _sofr_uri(uri: str) -> None:
    try:
        sofr_request_date(uri)
    except ValueError as error:
        raise SnapshotError(
            "SOURCE_QUERY_INVALID", "SOFR capture requires one canonical ISO date"
        ) from error


def _treasury_uri(uri: str) -> None:
    treasury_request_year(uri)


def _alfred_uri(uri: str) -> None:
    alfred_treasury_request(uri)


def _damodaran_uri(uri: str) -> None:
    damodaran_reference_profile(uri)


def _terms_uri(uri: str) -> None:
    parsed = urlsplit(uri)
    if parsed.query or parsed.fragment:
        raise SnapshotError(
            "SOURCE_QUERY_INVALID", "terms capture requires its exact registered URI"
        )


def _current_bea_uri(uri: str) -> None:
    if uri != BEA_CURRENT_GDP_URI:
        raise SnapshotError(
            "SOURCE_URI_NOT_ALLOWED", "current BEA GDP requires its exact workbook URI"
        )


def default_public_source_registrations() -> tuple[PublicSourceRegistration, ...]:
    """Assemble profiles here; transport and valuation know no concrete providers."""
    profiles: dict[str, PublicSourceCaptureProfilePort] = {
        **{
            source_id: RetainedAvailabilityCaptureProfile(
                _terms_uri, require_nonempty=True
            )
            for source_id in (
                "damodaran-use-terms",
                "bea-citation-terms",
                "us-government-works-terms",
                "new-york-fed-use-terms",
            )
        },
        "fred-observations": ProvidedAvailabilityCaptureProfile(require_nonempty=True),
        "bea-gdp-release": RetainedAvailabilityCaptureProfile(_bea_uri),
        "bea-nipa-archive": RetainedAvailabilityCaptureProfile(_bea_uri),
        "bea-nipa-current": RetainedAvailabilityCaptureProfile(
            _current_bea_uri, require_nonempty=True
        ),
        "damodaran-reference": RetainedAvailabilityCaptureProfile(
            _damodaran_uri, require_nonempty=True
        ),
        "new-york-fed-sofr": ReproducedMacroCaptureProfile(
            NewYorkFedSofrVintageProvider(),
            "us.sofr_overnight",
            NEW_YORK_FED_SOFR_PROFILE,
            _sofr_uri,
        ),
        "treasury-yields": ReproducedMacroCaptureProfile(
            TreasuryParYieldVintageProvider(),
            TREASURY_SERIES,
            TREASURY_PROFILE,
            _treasury_uri,
        ),
        "alfred-vintage": ReproducedMacroCaptureProfile(
            AlfredTreasuryVintageProvider(),
            TREASURY_SERIES,
            ALFRED_TREASURY_PROFILE,
            _alfred_uri,
        ),
    }
    provided = ProvidedAvailabilityCaptureProfile()
    return tuple(
        PublicSourceRegistration(spec, profiles.get(spec.source_id, provided))
        for spec in PUBLIC_SOURCE_SPECS
    )
