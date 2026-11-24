import pytest

from fundamental_service.data_releases import DataReleaseError
from fundamental_service.issuer_classification import reproduce_issuer_classification
from fundamental_service.sec_classification_source import (
    SecSubmissionClassificationProvider,
)
from fundamental_service.statement_issuer_scope import require_statement_issuer_scope
from test_issuer_classification import request, sec_submission


@pytest.mark.parametrize("sic", ["ELECTRONIC COMPUTERS [3571]", "SOFTWARE [7372]"])
def test_nonfinancial_scope_uses_original_sic_with_source_provenance(sic):
    classification = reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(),
        sources=(sec_submission(sic=sic),),
    )
    require_statement_issuer_scope(classification)
    assert classification.observation is not None
    assert classification.observation.accession_number == request().accession_number


@pytest.mark.parametrize("sic", ["BANK [6021]", "INSURANCE [6311]", "REIT [6798]"])
def test_financial_issuer_is_named_unsupported(sic):
    classification = reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(),
        sources=(sec_submission(sic=sic),),
    )
    with pytest.raises(DataReleaseError) as error:
        require_statement_issuer_scope(classification)
    assert error.value.code == "STATEMENT_FINANCIAL_ISSUER_UNSUPPORTED"


@pytest.mark.parametrize(
    "sources,changes",
    [
        ((), {}),
        ((sec_submission(sic=None),), {}),
        ((sec_submission(cik="0000789019"),), {}),
        ((sec_submission(),), {"accession_number": "0000320193-24-000124"}),
    ],
)
def test_missing_or_other_original_cannot_establish_company_scope(sources, changes):
    classification = reproduce_issuer_classification(
        SecSubmissionClassificationProvider(),
        request=request(**changes),
        sources=sources,
    )
    with pytest.raises(DataReleaseError) as error:
        require_statement_issuer_scope(classification)
    assert error.value.code == "STATEMENT_ISSUER_CLASSIFICATION_UNAVAILABLE"
