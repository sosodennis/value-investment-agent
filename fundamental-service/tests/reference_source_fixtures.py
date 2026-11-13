"""Synthetic workbook originals generated locally; no research data or live I/O."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import xlwt


def beta_xls(*, beta: float = 1.0024856714394297, change: str = "") -> bytes:
    book = xlwt.Workbook()
    sheet = book.add_sheet("Industry Averages")
    labels = {
        "A1": "Date updated:",
        "B3": "Beta, Unlevered beta and other risk measures",
        "F3": "US companies",
        "F8": "Marginal",
        "A10": "Industry Name",
        "B10": "Number of firms",
        "C10": "Beta ",
        "D10": "D/E Ratio",
        "E10": "Effective Tax rate",
        "F10": "Unlevered beta",
        "H10": "Unlevered beta corrected for cash",
        "A11": "Retail (Special Lines)",
        "A12": "Other industry",
        "A13": "Total Market",
        "A14": "Total Market (without financials)",
    }
    if change == "header":
        labels["F10"] = "Levered beta"
    if change == "duplicate":
        labels["A12"] = labels["A11"]
    for ref, text in labels.items():
        sheet.write(int(ref[1:]) - 1, ord(ref[0]) - ord("A"), text)
    sheet.write(0, 1, datetime(2025, 1, 5), xlwt.easyxf(num_format_str="M/D/YY"))
    sheet.write(8, 5, 0.25, xlwt.easyxf(num_format_str="0.00%"))
    style = xlwt.easyxf(num_format_str="0.00" if change != "precision" else "0.000")
    for row, value in ((10, beta), (12, 0.8), (13, 0.9)):
        sheet.write(row, 5, value, style)
    sheet.write(10, 2, 1.22, style)
    sheet.write(10, 7, 1.06, style)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def capital_xls(*, change: str = "") -> bytes:
    book = xlwt.Workbook()
    sheet = book.add_sheet("Industry Averages")
    definitions = book.add_sheet("Variables & FAQ")
    labels = {
        "A1": "Date updated:",
        "B3": "Cost of equity and capital (updateable)",
        "F3": "US companies",
        "A9": "Long Term Treasury bond rate =",
        "A10": "Risk Premium to Use for Equity =",
        "A11": "Global Default Spread to add to cost of debt =",
        "A12": "Do you want to use the marginal tax rate for cost of debt?",
        "A13": "If yes, enter the marginal tax rate to use",
        "A15": "These costs of capital are in US$. To convert to a different currency, please enter",
        "A19": "Industry Name",
        "B19": "Number of Firms",
        "C19": "Beta",
        "D19": "Cost of Equity",
        "E19": "E/(D+E)",
        "F19": "Std Dev in Stock",
        "G19": "Cost of Debt",
        "H19": "Tax Rate",
        "I19": "After-tax Cost of Debt",
        "J19": "D/(D+E)",
        "K19": "Cost of Capital",
        "L19": "Cost of Capital (Local Currency)",
        "F12": "Yes",
    }
    if change == "header":
        labels["G19"] = "After-tax Cost of Debt"
    if change == "currency":
        labels["A15"] = "These costs of capital are in euros"
    if change == "population":
        labels["F3"] = "Global companies"
    if change == "tax_basis":
        labels["F12"] = "No"
    for ref, text in labels.items():
        sheet.write(int(ref[1:]) - 1, ord(ref[0]) - ord("A"), text)
    sheet.write(
        0,
        1,
        datetime(2027 if change == "future" else 2025, 1, 5),
        xlwt.easyxf(num_format_str="M/D/YY"),
    )
    for row, col, value in ((8, 3, 0.0458), (9, 3, 0.0433), (10, 3, 0), (12, 5, 0.25)):
        sheet.write(row, col, 2.0 if change == "context_domain" else value)
    for row, name in (
        (19, "Retail (Special Lines)"),
        (20, "Missing industry"),
        (21, "Total Market"),
        (22, "Total Market (without financials)"),
    ):
        if change == "gap" and row == 20:
            continue
        sheet.write(
            row,
            0,
            "Retail (Special Lines)" if change == "duplicate" and row == 20 else name,
        )
        if row == 20:
            continue
        for col, value in (
            (2, 1.23),
            (3, 0.98),
            (4, 0.775),
            (6, 0.0578),
            (8, 0.04335),
            (9, 0.225),
        ):
            if change == "domain" and col == 9:
                value = 1.01
            style = "0.00" if col == 2 else "0.00%"
            if change == "precision" and col == 6:
                style = "0.000%"
            sheet.write(row, col, value, xlwt.easyxf(num_format_str=style))
    for row, variable, method in (
        (4, "Beta", "Average regression beta across companies in the group."),
        (
            6,
            "D/(D+E)",
            "Total Debt (including lease debt)/ (Total Debt (including lease debt)+ Market Cap), aggregated across all firms in group, with all numbers other than market cap coming from most recent balance sheet; market cap is as of last day of the most recent year.",
        ),
        (
            7,
            "Cost of debt",
            "Pre-tax cost of borrowing for sector, estimated based upon the standard deviation of equity.",
        ),
    ):
        definitions.write(row, 0, variable)
        definitions.write(row, 1, "Different method" if change == "method" else method)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def country_xlsx(*, change: str = "", revised: bool = False) -> bytes:
    def text(ref: str, value: str) -> str:
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'

    def number(ref: str, value: str, *, formula: bool = False) -> str:
        return (
            f'<c r="{ref}" s="1">'
            + ("<f>1+1</f>" if formula else "")
            + f"<v>{value}</v></c>"
        )

    erp = {
        1: text("A1", "Country and Equity Risk Premiums"),
        2: text("A2", "Date of update:") + '<c r="B2"><v>44196</v></c>',
        7: "".join(
            text(ref, value)
            for ref, value in (
                ("A7", "Country"),
                ("D7", "Rating-based Default Spread"),
                ("E7", "Total Equity Risk Premium"),
                ("F7", "Country Risk Premium"),
                ("H7", "Total Equity Risk Premium2"),
            )
        ),
        8: text("A8", "United States")
        + number("E8", "4.3299999999999998E-2", formula=change == "formula")
        + number("H8", "0.99"),
        9: text("A9", "Missing country") + text("E9", "NA"),
        10: text("A10", "Frontier Markets (no sovereign ratings)"),
        11: text("A11", "Country") + text("B11", "PRS Composite Risk Score"),
        12: text("A12", "United States") + number("C12", "0.8") + number("E12", "0.9"),
    }
    if change == "header":
        erp[7] = erp[7].replace("Total Equity Risk Premium</t>", "CDS-based ERP</t>")
    if change == "duplicate":
        erp[9] = erp[9].replace("Missing country", "United States")
    if change == "nonfinite":
        erp[8] = erp[8].replace("4.3299999999999998E-2", "NaN")
    if change == "unknown":
        erp[9] = erp[9].replace(">NA<", ">surprise<")
    if change == "future":
        erp[2] = erp[2].replace("44196", "50000")
    if change == "gap":
        erp[8] = ""
    if revised:
        erp = {
            row + 1 if row >= 7 else row: (
                re.sub(
                    r'r="([A-Z]+)([0-9]+)"',
                    lambda match: f'r="{match[1]}{int(match[2]) + 1}"',
                    cells,
                )
                if row >= 7
                else cells
            )
            for row, cells in erp.items()
        }
        erp[2] += text("C2", "Updated February for sovereign ratings")
        erp[3] = (
            text("A3", "Enter the current risk premium for a mature equity market")
            + number("E3", "0.04")
            + text("F3", "Implied ERP with adjusted dollar riskfree rate")
        )
        erp[4] = (
            text("A4", "Enter the current risk premium for the US =")
            + number("E4", "0.0433")
            + text("F4", "US equity risk premium computed using implied ERP approach")
        )
        erp[5] = text(
            "A5",
            "Do you want to adjust the country default spread for the additional volatility of the equity market to get to a country premium?",
        ) + text("E5", "No" if change == "method" else "Yes")
        erp[6] = text(
            "A6",
            "If yes, enter the multiplier to use on the default spread (See worksheet for volatility numbers for selected emerging markets)",
        ) + (
            '<c r="E6"><v>1.5</v></c>'
            if change == "context_precision"
            else '<c r="E6" s="2"><v>1.5</v></c>'
        )
        if change == "context_missing":
            erp[3] = erp[3].replace("<v>0.04</v>", "")
    tax = {
        1: text("A1", "Country")
        + text("B1", "Tax Rate")
        + text("C1", "Looked up for 2023"),
        2: text("A2", "United States") + number("B2", "0.25"),
        3: text("A3", "Missing country"),
        4: text("E4", "United States") + number("F4", "0.99"),
    }

    def sheet(rows: dict[int, str]) -> str:
        return (
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(f'<row r="{r}">{cells}</row>' for r, cells in rows.items())
            + "</sheetData></worksheet>"
        )

    parts = {
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="1"/><sheets><sheet name="ERPs by country" sheetId="1" r:id="rId1"/><sheet name="Country Tax Rates" sheetId="2" r:id="rId2"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in (1, 2)
        )
        + "</Relationships>",
        "xl/styles.xml": '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="10"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": sheet(erp),
        "xl/worksheets/sheet2.xml": sheet(tax),
    }
    if revised:
        parts["xl/styles.xml"] = (
            parts["xl/styles.xml"]
            .replace('count="2"', 'count="3"')
            .replace("</cellXfs>", '<xf numFmtId="2"/></cellXfs>')
        )
    if change == "precision":
        parts["xl/styles.xml"] = parts["xl/styles.xml"].replace(
            'numFmtId="10"', 'numFmtId="9"'
        )
    if change == "external":
        parts["xl/_rels/workbook.xml.rels"] = parts[
            "xl/_rels/workbook.xml.rels"
        ].replace(
            'Target="worksheets/sheet1.xml"',
            'TargetMode="External" Target="https://example.test/sheet.xml"',
        )
    if change == "duplicate_cell":
        parts["xl/worksheets/sheet1.xml"] = parts["xl/worksheets/sheet1.xml"].replace(
            '<c r="E8" s="1">', number("E8", "0.2") + '<c r="E8" s="1">'
        )
    if change == "doctype":
        parts["xl/workbook.xml"] = (
            '<!DOCTYPE workbook [<!ENTITY x "unsafe">]>' + parts["xl/workbook.xml"]
        )
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, payload in sorted(parts.items()):
            info = ZipInfo(name, (2025, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, payload)
    return output.getvalue()
