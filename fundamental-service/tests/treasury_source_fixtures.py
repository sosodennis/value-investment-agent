"""Small synthetic provider responses; no live downloads or policy approvals."""

TREASURY_URI = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2025"
)
ALFRED_URI = (
    "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
    "?id=DGS10&cosd=2025-03-28&coed=2025-03-31&vintage_date=2025-03-31"
)
ALFRED_CSV = b"observation_date,DGS10_20250331\n2025-03-28,4.27\n"
TREASURY_XML = b"""<feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"
 xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
 <title type="text">DailyTreasuryYieldCurveRateData</title>
 <entry><content type="application/xml"><m:properties>
 <d:NEW_DATE m:type="Edm.DateTime">2025-03-28T00:00:00</d:NEW_DATE>
 <d:BC_10YEAR m:type="Edm.Double">4.27</d:BC_10YEAR>
 </m:properties></content></entry></feed>"""
