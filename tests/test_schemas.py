import pytest
from pydantic import ValidationError

from common import nda
from common.schemas import Extraction, NdaFields, is_optional
from tests.conftest import absent, sample_nda_answer


def test_nda_constants_match_the_model():
    optional = {name for name in NdaFields.model_fields if is_optional(NdaFields, name)}
    assert optional == set(nda.OPTIONAL_FIELDS)
    assert nda.DATE_FIELDS <= set(NdaFields.model_fields)


def test_valid_nda_answer():
    parsed = Extraction.model_validate(sample_nda_answer(), context={"page_count": 2})
    assert parsed.nda_fields.term_months.value == 6


def test_nda_without_fields_is_rejected():
    answer = sample_nda_answer()
    answer["nda_fields"] = None
    with pytest.raises(ValidationError):
        Extraction.model_validate(answer)


def test_non_nda_drops_any_fields():
    answer = sample_nda_answer()
    answer["classification"].update(doc_type="other", subtype="invoice")
    assert Extraction.model_validate(answer).nda_fields is None


def test_value_without_a_quote_is_rejected():
    answer = sample_nda_answer(governing_law={"value": "Delaware", "page": 1, "quote": None, "confidence": 0.9})
    with pytest.raises(ValidationError):
        Extraction.model_validate(answer)


def test_page_outside_the_document_is_rejected():
    answer = sample_nda_answer()
    answer["classification"]["page"] = 9
    with pytest.raises(ValidationError):
        Extraction.model_validate(answer, context={"page_count": 2})


def test_false_residuals_means_absent():
    answer = sample_nda_answer(residuals_clause={"value": False, "page": None, "quote": None, "confidence": 0.9})
    assert Extraction.model_validate(answer).nda_fields.residuals_clause.value is None
    assert absent()["value"] is None
