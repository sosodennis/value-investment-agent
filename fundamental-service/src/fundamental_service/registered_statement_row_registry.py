"""Reviewed primary statement row locators; no reported amounts."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PrimaryStatementRowLocator:
    row_id: str
    table_index: int
    row_index: int
    context_ids: tuple[str, ...]


@dataclass(frozen=True)
class PrimaryStatementScope:
    raw_content_hash: str
    annual_periods: tuple[tuple[date, date], ...]
    revenue_concept: str
    cash_balance_concept: str
    cash_change_concept: str
    cash_effect_concept: str | None
    parser_input_hash: str
    locators: tuple[PrimaryStatementRowLocator, ...]

    def concept_for(self, row_id: str) -> str | None:
        if row_id == "revenue":
            return self.revenue_concept
        if row_id in {"cash_flow_beginning_balance", "cash_flow_ending_balance"}:
            return self.cash_balance_concept
        if row_id == "net_change_in_cash":
            return self.cash_change_concept
        if row_id == "effect_of_exchange_rates_on_cash":
            return self.cash_effect_concept
        return None


PRIMARY_STATEMENTS = {
    ("0000320193", "0000320193-20-000096"): PrimaryStatementScope(
        "247d6a992380d121caf77d37efa77d39572fb0e93e78537e9ba3f8e45d4f5fd2",
        (
            (date(2017, 10, 1), date(2018, 9, 29)),
            (date(2018, 9, 30), date(2019, 9, 28)),
            (date(2019, 9, 29), date(2020, 9, 26)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        None,
        "cffb9c248ad2faea24d5568bdf40453b5fa3a72cc0ca87f1d4d6af050bc60e24",
        (
            PrimaryStatementRowLocator(
                "revenue",
                25,
                6,
                (
                    "i223bd574caab4f739f73936be6065c72_D20190929-20200926",
                    "i4920908218084be688c8fa96b8903033_D20171001-20180929",
                    "i5085fb79a9a14a9aae9b909beb32bce2_D20180930-20190928",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                29,
                3,
                (
                    "i63b2d6cbc1b74217a23ffa0b1fb32a03_I20180929",
                    "ic162192758c540a496b78579d45ae11a_I20170930",
                    "ic363a9ee75bd48f88800fc5dadba8293_I20190928",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                29,
                41,
                (
                    "i63b2d6cbc1b74217a23ffa0b1fb32a03_I20180929",
                    "i747bec89b4e84f74ae3445db3509f609_I20200926",
                    "ic363a9ee75bd48f88800fc5dadba8293_I20190928",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                29,
                40,
                (
                    "i223bd574caab4f739f73936be6065c72_D20190929-20200926",
                    "i4920908218084be688c8fa96b8903033_D20171001-20180929",
                    "i5085fb79a9a14a9aae9b909beb32bce2_D20180930-20190928",
                ),
            ),
        ),
    ),
    ("0000320193", "0000320193-21-000105"): PrimaryStatementScope(
        "c21f651f9bb94b1d78944a9e91a263bcead4b417131ae797a46fee37d4d452b0",
        (
            (date(2018, 9, 30), date(2019, 9, 28)),
            (date(2019, 9, 29), date(2020, 9, 26)),
            (date(2020, 9, 27), date(2021, 9, 25)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        None,
        "2e514610fe34679232a027dc955d6eec2ab65b96bf1adfa985d199cbdafdaad2",
        (
            PrimaryStatementRowLocator(
                "revenue",
                22,
                6,
                (
                    "i2733dd6a703747959fe733d5ba17971f_D20180930-20190928",
                    "i55e5364a9af5491886caee077afe8d44_D20200927-20210925",
                    "i725ce765160e48a2a3b36989bda2ca94_D20190929-20200926",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                26,
                3,
                (
                    "i694dd514ebaa44a4a71e585cc7f559d7_I20190928",
                    "i6d507af9a8294eb39264b0e7c0c0b226_I20200926",
                    "ib79160224f074258b67db5ce1b24c0d3_I20180929",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                26,
                41,
                (
                    "i0dc4fee6389a45cfaf1b2c28d7258d49_I20210925",
                    "i694dd514ebaa44a4a71e585cc7f559d7_I20190928",
                    "i6d507af9a8294eb39264b0e7c0c0b226_I20200926",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                26,
                40,
                (
                    "i2733dd6a703747959fe733d5ba17971f_D20180930-20190928",
                    "i55e5364a9af5491886caee077afe8d44_D20200927-20210925",
                    "i725ce765160e48a2a3b36989bda2ca94_D20190929-20200926",
                ),
            ),
        ),
    ),
    ("0000320193", "0000320193-22-000108"): PrimaryStatementScope(
        "b93dafe086e54e1e6bccffc5cd31bc9443b69ef3157a7b7e0d9dedef2ef61385",
        (
            (date(2019, 9, 29), date(2020, 9, 26)),
            (date(2020, 9, 27), date(2021, 9, 25)),
            (date(2021, 9, 26), date(2022, 9, 24)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        None,
        "5e85037df8503e65c35a8e92179eeacbe0f318ce508f590a14debb1f50cf219c",
        (
            PrimaryStatementRowLocator(
                "revenue",
                22,
                6,
                (
                    "i31bf5094819a46b79a45ba71ba807c86_D20200927-20210925",
                    "i4a4fb50fc2db4070adb20304175890ef_D20210926-20220924",
                    "idaa220573a164e6f8ce0fa26f32a2bdb_D20190929-20200926",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                26,
                3,
                (
                    "i4e82d58a300a4a309eacd18ec8c3e8c7_I20210925",
                    "ie7ecd9e3779740ccb2ce950be91c4cb8_I20190928",
                    "if6a94bdcde96419d955ae2ba7b1e954a_I20200926",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                26,
                38,
                (
                    "i4e82d58a300a4a309eacd18ec8c3e8c7_I20210925",
                    "if3ba800b42a9406abf364f6d45d67e23_I20220924",
                    "if6a94bdcde96419d955ae2ba7b1e954a_I20200926",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                26,
                37,
                (
                    "i31bf5094819a46b79a45ba71ba807c86_D20200927-20210925",
                    "i4a4fb50fc2db4070adb20304175890ef_D20210926-20220924",
                    "idaa220573a164e6f8ce0fa26f32a2bdb_D20190929-20200926",
                ),
            ),
        ),
    ),
    ("0000320193", "0000320193-23-000106"): PrimaryStatementScope(
        "c53b281e007596cfc861f3ad72e8eddcdce2908c8c51e4cc67d9555aaf83b568",
        (
            (date(2020, 9, 27), date(2021, 9, 25)),
            (date(2021, 9, 26), date(2022, 9, 24)),
            (date(2022, 9, 25), date(2023, 9, 30)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        None,
        "c12269ed56c9fa19b96450e845b356b99b2f24f1e90800804112625cd1ac948f",
        (
            PrimaryStatementRowLocator("revenue", 22, 6, ("c-1", "c-20", "c-21")),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance", 26, 3, ("c-23", "c-24", "c-25")
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance", 26, 41, ("c-22", "c-23", "c-24")
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash", 26, 40, ("c-1", "c-20", "c-21")
            ),
        ),
    ),
    ("0000320193", "0000320193-24-000123"): PrimaryStatementScope(
        "40c460d3eed32c7394fe651374bb2a6c43f5082098d1a32d5e7516d50110b0bb",
        (
            (date(2021, 9, 26), date(2022, 9, 24)),
            (date(2022, 9, 25), date(2023, 9, 30)),
            (date(2023, 10, 1), date(2024, 9, 28)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        None,
        "a051b50fcba8c752df3dd55a87f42e0fb1c8f31b7b8ed287f55c8c385849e159",
        (
            PrimaryStatementRowLocator("revenue", 22, 6, ("c-1", "c-19", "c-20")),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance", 26, 3, ("c-22", "c-23", "c-24")
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance", 26, 41, ("c-21", "c-22", "c-23")
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash", 26, 40, ("c-1", "c-19", "c-20")
            ),
        ),
    ),
    ("0000320193", "0000320193-25-000079"): PrimaryStatementScope(
        "96d412db63c241eeae57639bf03e040d774ed991442733c9a140e89739abbe8d",
        (
            (date(2022, 9, 25), date(2023, 9, 30)),
            (date(2023, 10, 1), date(2024, 9, 28)),
            (date(2024, 9, 29), date(2025, 9, 27)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        None,
        "274361a794f84b24d75b4ee98bc8eff5a031b4fc1be1a1210dbc2b10d92c5179",
        (
            PrimaryStatementRowLocator("revenue", 22, 6, ("c-1", "c-18", "c-19")),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance", 26, 3, ("c-21", "c-22", "c-23")
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance", 26, 40, ("c-20", "c-21", "c-22")
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash", 26, 39, ("c-1", "c-18", "c-19")
            ),
        ),
    ),
    ("0000320193", "0000320193-26-000026"): PrimaryStatementScope(
        "502cdd211c5335ef05b94f58e84bedb6cf5d58489c934feb92d77d194998cdbd",
        (
            (date(2023, 10, 1), date(2024, 9, 28)),
            (date(2024, 9, 29), date(2025, 9, 27)),
            (date(2025, 9, 28), date(2026, 9, 26)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        None,
        "13c3d5a46a897d1249f38987bdf300232d0fca9eb273d79dae5af64b6987e5b1",
        (
            PrimaryStatementRowLocator("revenue", 22, 6, ("c-1", "c-17", "c-18")),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance", 26, 3, ("c-20", "c-21", "c-22")
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance", 26, 40, ("c-19", "c-20", "c-21")
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash", 26, 39, ("c-1", "c-17", "c-18")
            ),
        ),
    ),
    ("0000789019", "0000950170-23-035122"): PrimaryStatementScope(
        "5ac3868026e907cd8316298af5bd88b095ed0f1dd6b5580b507bcb9fe2cfc6dd",
        (
            (date(2020, 7, 1), date(2021, 6, 30)),
            (date(2021, 7, 1), date(2022, 6, 30)),
            (date(2022, 7, 1), date(2023, 6, 30)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
        "40a63448cf7d8380c528d6df039e722270ae0d19fc9c7450226a396eb83d20e3",
        (
            PrimaryStatementRowLocator(
                "revenue",
                24,
                11,
                (
                    "C_4e8ad330-b4ec-4b1c-975b-18c89babf3f1",
                    "C_da7a1266-ce2b-41b7-83ff-bb6e03dc1fa5",
                    "C_efe853fc-8e8a-4899-b65b-e33c17faff7c",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                27,
                56,
                (
                    "C_1b8b2ebd-1e34-4a4c-b73e-85909bda8965",
                    "C_bb0f3efa-a17d-4fad-ac0a-bcd262c82077",
                    "C_c0e12f72-c285-4bcf-b8be-db117bbc796a",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                27,
                59,
                (
                    "C_bb0f3efa-a17d-4fad-ac0a-bcd262c82077",
                    "C_c0e12f72-c285-4bcf-b8be-db117bbc796a",
                    "C_d4129f7a-27bd-4daf-8d40-6ace4c3b7548",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                27,
                55,
                (
                    "C_4e8ad330-b4ec-4b1c-975b-18c89babf3f1",
                    "C_da7a1266-ce2b-41b7-83ff-bb6e03dc1fa5",
                    "C_efe853fc-8e8a-4899-b65b-e33c17faff7c",
                ),
            ),
            PrimaryStatementRowLocator(
                "effect_of_exchange_rates_on_cash",
                27,
                52,
                (
                    "C_4e8ad330-b4ec-4b1c-975b-18c89babf3f1",
                    "C_da7a1266-ce2b-41b7-83ff-bb6e03dc1fa5",
                    "C_efe853fc-8e8a-4899-b65b-e33c17faff7c",
                ),
            ),
        ),
    ),
    ("0000789019", "0000950170-24-087843"): PrimaryStatementScope(
        "321fd42528989d20b979a438c1fd185260e45e4c902a9089524aad1e6146f65d",
        (
            (date(2021, 7, 1), date(2022, 6, 30)),
            (date(2022, 7, 1), date(2023, 6, 30)),
            (date(2023, 7, 1), date(2024, 6, 30)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
        "01cc7750e904e14a2065ba0ddb639138f2e5b0591c8071a513ac1234a735602e",
        (
            PrimaryStatementRowLocator(
                "revenue",
                24,
                11,
                (
                    "C_6dbdb3a2-9baf-41b4-922d-f59879124337",
                    "C_ae7e339c-3219-4fd1-a57c-be06046f6b58",
                    "C_ed99bc14-2e8b-442d-834c-3815de823d07",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                27,
                57,
                (
                    "C_005805a9-264e-4b1d-93ea-497c67cc9a68",
                    "C_61840f93-8c71-4a1c-b3d3-94ecb06d6232",
                    "C_d9f97fb3-b311-45ac-a050-051db066016d",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                27,
                60,
                (
                    "C_005805a9-264e-4b1d-93ea-497c67cc9a68",
                    "C_910b395a-5d62-4894-aa42-1da4086261cc",
                    "C_d9f97fb3-b311-45ac-a050-051db066016d",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                27,
                56,
                (
                    "C_6dbdb3a2-9baf-41b4-922d-f59879124337",
                    "C_ae7e339c-3219-4fd1-a57c-be06046f6b58",
                    "C_ed99bc14-2e8b-442d-834c-3815de823d07",
                ),
            ),
            PrimaryStatementRowLocator(
                "effect_of_exchange_rates_on_cash",
                27,
                53,
                (
                    "C_6dbdb3a2-9baf-41b4-922d-f59879124337",
                    "C_ae7e339c-3219-4fd1-a57c-be06046f6b58",
                    "C_ed99bc14-2e8b-442d-834c-3815de823d07",
                ),
            ),
        ),
    ),
    ("0000789019", "0000950170-25-100235"): PrimaryStatementScope(
        "bd12d1d000a291b2169e28cfc9e56dc38a7f3a8ef0ff78706c3df7fe042e5698",
        (
            (date(2022, 7, 1), date(2023, 6, 30)),
            (date(2023, 7, 1), date(2024, 6, 30)),
            (date(2024, 7, 1), date(2025, 6, 30)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
        "7475ad82dc11fc5e27bdbea995b44da0545778b966725ba42524953e4ac9ce2c",
        (
            PrimaryStatementRowLocator(
                "revenue",
                23,
                11,
                (
                    "C_7102029d-8d6c-44c5-b166-04cf41443b1e",
                    "C_c19fe6c0-0e87-44b0-aa2a-d9c6e40a5862",
                    "C_deaa7eaf-e13f-4828-9e73-3d077f8605da",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                26,
                57,
                (
                    "C_4c21aa3d-5500-44db-8595-869cbaf925e6",
                    "C_670413aa-499b-43fb-803c-735d0fc51f59",
                    "C_b1a183df-e4a5-492b-ab7e-1bbec2052a42",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                26,
                60,
                (
                    "C_4c21aa3d-5500-44db-8595-869cbaf925e6",
                    "C_670413aa-499b-43fb-803c-735d0fc51f59",
                    "C_f6acec30-41ed-4918-bef7-c8a710bf3a7a",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                26,
                56,
                (
                    "C_7102029d-8d6c-44c5-b166-04cf41443b1e",
                    "C_c19fe6c0-0e87-44b0-aa2a-d9c6e40a5862",
                    "C_deaa7eaf-e13f-4828-9e73-3d077f8605da",
                ),
            ),
            PrimaryStatementRowLocator(
                "effect_of_exchange_rates_on_cash",
                26,
                53,
                (
                    "C_7102029d-8d6c-44c5-b166-04cf41443b1e",
                    "C_c19fe6c0-0e87-44b0-aa2a-d9c6e40a5862",
                    "C_deaa7eaf-e13f-4828-9e73-3d077f8605da",
                ),
            ),
        ),
    ),
    ("0000789019", "0001193125-26-323660"): PrimaryStatementScope(
        "e4289989cfa36551f347a28312cb21ac4ca272816e03c90c11b0673862dc0a0d",
        (
            (date(2023, 7, 1), date(2024, 6, 30)),
            (date(2024, 7, 1), date(2025, 6, 30)),
            (date(2025, 7, 1), date(2026, 6, 30)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
        "4561138eb81082fd06a693e6a2036eeae14e321d0c75a77aee5c28f1d4dc6d1d",
        (
            PrimaryStatementRowLocator(
                "revenue",
                24,
                11,
                (
                    "C_29985a27-1d12-4b7e-9a06-156523f6e71e",
                    "C_7575f467-7692-4974-a3da-f27e7e8e1c47",
                    "C_7f83b284-3c69-4779-90ec-f0c89f19f47e",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                27,
                57,
                (
                    "C_528a2210-872f-4ed7-b006-dd38f90dd456",
                    "C_add39d2a-5312-489c-8f09-a58486fcc59d",
                    "C_e82193ee-f8f3-4426-ab64-d890279a5222",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                27,
                60,
                (
                    "C_528a2210-872f-4ed7-b006-dd38f90dd456",
                    "C_ca004a37-7abb-4b0e-8638-a7c6b14ebb45",
                    "C_e82193ee-f8f3-4426-ab64-d890279a5222",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                27,
                56,
                (
                    "C_29985a27-1d12-4b7e-9a06-156523f6e71e",
                    "C_7575f467-7692-4974-a3da-f27e7e8e1c47",
                    "C_7f83b284-3c69-4779-90ec-f0c89f19f47e",
                ),
            ),
            PrimaryStatementRowLocator(
                "effect_of_exchange_rates_on_cash",
                27,
                53,
                (
                    "C_29985a27-1d12-4b7e-9a06-156523f6e71e",
                    "C_7575f467-7692-4974-a3da-f27e7e8e1c47",
                    "C_7f83b284-3c69-4779-90ec-f0c89f19f47e",
                ),
            ),
        ),
    ),
    ("0000789019", "0001564590-20-034944"): PrimaryStatementScope(
        "99d1dfdd564d8e7cc42fa9c6c3b44c0bc131fece7e6638f28e24ec7cb49faa7a",
        (
            (date(2017, 7, 1), date(2018, 6, 30)),
            (date(2018, 7, 1), date(2019, 6, 30)),
            (date(2019, 7, 1), date(2020, 6, 30)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashAndCashEquivalents",
        "47985d3dbaf1c244b78622fb960637e137c7afff506630dfff05fbbb20c7c249",
        (
            PrimaryStatementRowLocator(
                "revenue",
                152,
                10,
                (
                    "C_0000789019_20170701_20180630",
                    "C_0000789019_20180701_20190630",
                    "C_0000789019_20190701_20200630",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                155,
                57,
                (
                    "C_0000789019_20170630",
                    "C_0000789019_20180630",
                    "C_0000789019_20190630",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                155,
                60,
                (
                    "C_0000789019_20180630",
                    "C_0000789019_20190630",
                    "C_0000789019_20200630",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                155,
                56,
                (
                    "C_0000789019_20170701_20180630",
                    "C_0000789019_20180701_20190630",
                    "C_0000789019_20190701_20200630",
                ),
            ),
            PrimaryStatementRowLocator(
                "effect_of_exchange_rates_on_cash",
                155,
                53,
                (
                    "C_0000789019_20170701_20180630",
                    "C_0000789019_20180701_20190630",
                    "C_0000789019_20190701_20200630",
                ),
            ),
        ),
    ),
    ("0000789019", "0001564590-21-039151"): PrimaryStatementScope(
        "0168b995b37d463102f295f989710294eb61b98db1636a9384ea1ccc276dddcb",
        (
            (date(2018, 7, 1), date(2019, 6, 30)),
            (date(2019, 7, 1), date(2020, 6, 30)),
            (date(2020, 7, 1), date(2021, 6, 30)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashAndCashEquivalents",
        "0da1de4fd579befeed21d486d8840e78014df54b72d420e2a219d23f8019367c",
        (
            PrimaryStatementRowLocator(
                "revenue",
                138,
                10,
                (
                    "C_0000789019_20180701_20190630",
                    "C_0000789019_20190701_20200630",
                    "C_0000789019_20200701_20210630",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                141,
                55,
                (
                    "C_0000789019_20180630",
                    "C_0000789019_20190630",
                    "C_0000789019_20200630",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                141,
                58,
                (
                    "C_0000789019_20190630",
                    "C_0000789019_20200630",
                    "C_0000789019_20210630",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                141,
                54,
                (
                    "C_0000789019_20180701_20190630",
                    "C_0000789019_20190701_20200630",
                    "C_0000789019_20200701_20210630",
                ),
            ),
            PrimaryStatementRowLocator(
                "effect_of_exchange_rates_on_cash",
                141,
                51,
                (
                    "C_0000789019_20180701_20190630",
                    "C_0000789019_20190701_20200630",
                    "C_0000789019_20200701_20210630",
                ),
            ),
        ),
    ),
    ("0000789019", "0001564590-22-026876"): PrimaryStatementScope(
        "2732aabedd18ec1709b1b0f9144d4e99fee4e3788453626f4efa01b9cbc2b749",
        (
            (date(2019, 7, 1), date(2020, 6, 30)),
            (date(2020, 7, 1), date(2021, 6, 30)),
            (date(2021, 7, 1), date(2022, 6, 30)),
        ),
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
        "b47cf32cd71e13d858eb568b8b1013c5289c98edabbc54071cecbf34d29451fc",
        (
            PrimaryStatementRowLocator(
                "revenue",
                149,
                10,
                (
                    "C_0000789019_20190701_20200630",
                    "C_0000789019_20200701_20210630",
                    "C_0000789019_20210701_20220630",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_beginning_balance",
                152,
                55,
                (
                    "C_0000789019_20190630",
                    "C_0000789019_20200630",
                    "C_0000789019_20210630",
                ),
            ),
            PrimaryStatementRowLocator(
                "cash_flow_ending_balance",
                152,
                58,
                (
                    "C_0000789019_20200630",
                    "C_0000789019_20210630",
                    "C_0000789019_20220630",
                ),
            ),
            PrimaryStatementRowLocator(
                "net_change_in_cash",
                152,
                54,
                (
                    "C_0000789019_20190701_20200630",
                    "C_0000789019_20200701_20210630",
                    "C_0000789019_20210701_20220630",
                ),
            ),
            PrimaryStatementRowLocator(
                "effect_of_exchange_rates_on_cash",
                152,
                51,
                (
                    "C_0000789019_20190701_20200630",
                    "C_0000789019_20200701_20210630",
                    "C_0000789019_20210701_20220630",
                ),
            ),
        ),
    ),
}
