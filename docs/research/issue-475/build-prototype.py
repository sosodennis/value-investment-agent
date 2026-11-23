import json
import re
import pathlib
from decimal import Decimal, ROUND_HALF_UP

out = pathlib.Path(__file__).resolve().parent
root = out.parents[2]
data = json.loads((out / "sample.json").read_text())


def fixed(v, shift=0):
    return f'{(Decimal(v)*Decimal(10)**shift).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP):,.2f}'


def b(v):
    return fixed(Decimal(v) / Decimal(10) ** 9)


for row in data["forecasts"]:
    row["display"] = {k: b(row[k]) for k in ["revenue", "fcff", "discounted_fcff"]}
for scenario in data["scenario_results"]:
    scenario["display"] = fixed(scenario["per_share_value"])
for row in data["historical_revenue"]:
    row["display"] = b(row["value"])
data["display"] = {
    "base": fixed(data["per_share_value"]),
    "median": fixed(data["quantiles"]["p50"]),
    "p05": fixed(data["quantiles"]["p05"]),
    "p95": fixed(data["quantiles"]["p95"]),
    "wacc": fixed(data["wacc"], 2),
    "growth": fixed(data["assumptions"]["terminal_growth"], 2),
    "revision": fixed(data["revision"]["per_share_value"]),
    "equity": fixed(Decimal(data["intrinsic_value"]) / Decimal(10) ** 12),
}
css = (root / "frontend/src/app/globals.css").read_text()
tokens = "\n".join(
    re.search(p, css, re.S).group() for p in [r":root \{.*?\n\}", r"\.dark \{.*?\n\}"]
)
html = (
    (out / "prototype.template.html")
    .read_text()
    .replace("TOKEN_CSS", tokens)
    .replace("SAMPLE_DATA", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
)
(out / "prototype.html").write_text(html)
