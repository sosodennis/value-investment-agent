import json

from fundamental_service.source_acquisition import SecAcquisitionUseCase


def test_sec_filing_index_selects_only_primary_schema_and_linkbases():
    payload = json.dumps(
        {
            "directory": {
                "item": [
                    {
                        "name": "aapl-20240928.htm",
                        "type": "text.gif",
                        "size": "1503780",
                    },
                    {"name": "aapl-20240928.xsd", "type": "text.gif", "size": "58200"},
                    {
                        "name": "aapl-20240928_cal.xml",
                        "type": "text.gif",
                        "size": "150261",
                    },
                    {
                        "name": "aapl-20240928_def.xml",
                        "type": "text.gif",
                        "size": "232678",
                    },
                    {
                        "name": "aapl-20240928_lab.xml",
                        "type": "text.gif",
                        "size": "779708",
                    },
                    {
                        "name": "aapl-20240928_pre.xml",
                        "type": "text.gif",
                        "size": "509625",
                    },
                    {
                        "name": "a10-kexhibit10199282024.htm",
                        "type": "text.gif",
                        "size": "56948",
                    },
                    {"name": "other-issuer.xsd", "type": "EX-101.SCH", "size": "1000"},
                ]
            }
        }
    ).encode()
    use_case = object.__new__(SecAcquisitionUseCase)

    assert use_case._select_dts_filenames(payload, "aapl-20240928.htm") == (
        "aapl-20240928.xsd",
        "aapl-20240928_cal.xml",
        "aapl-20240928_def.xml",
        "aapl-20240928_lab.xml",
        "aapl-20240928_pre.xml",
    )
