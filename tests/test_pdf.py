import pytest

from common.errors import PermanentError
from common.pdf import parse_pdf


def test_parses_text_page_by_page(sample_doc):
    assert sample_doc.page_count == 2
    assert [p.number for p in sample_doc.pages] == [1, 2]
    assert "Mutual Non-Disclosure Agreement" in sample_doc.pages[0].norm_text
    assert not sample_doc.partial


def test_page_limit_marks_the_document_partial(sample_pdf):
    doc = parse_pdf(sample_pdf, max_pages=1)
    assert len(doc.pages) == 1
    assert doc.page_count == 2
    assert doc.partial


def test_garbage_is_a_permanent_error():
    with pytest.raises(PermanentError):
        parse_pdf(b"this is not a pdf")
