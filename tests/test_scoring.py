import json

from common import llm
from common.doctext import DocText, PageText
from common.playbook import load_playbook
from common.scoring import score_document
from tests.conftest import ROOT, FakeExtractor, absent, cited, sample_nda_answer

RULES = load_playbook(ROOT / "src" / "score" / "nda_playbook.yaml")


def run(doc, payload, stop_reason="end_turn"):
    response = FakeExtractor(payload, stop_reason).complete("", "", 1)
    extraction = llm.interpret(response, doc)
    return extraction, score_document(doc, extraction, RULES)


def reason_codes(result):
    return {(r["code"], r["field"]) for r in result["reasons"]}


def test_standard_nda_is_auto_approved(sample_doc):
    extraction, result = run(sample_doc, sample_nda_answer())
    assert extraction["outcome"] == "ok"
    assert result["reasons"] == []
    assert result["risk"] == "low"
    assert result["confidence"] == 0.95
    assert result["auto_approve"] is True


def test_playbook_deviation_needs_review(sample_doc):
    # Say the term is 36 months and quote text that really says so.
    doc = DocText(1, [PageText(1, sample_doc.pages[0].raw_text.replace("six (6) months", "thirty-six (36) months"))])
    answer = sample_nda_answer(term_months=cited(36, 1, "shall remain in effect for thirty-six (36) months from the"))
    _, result = run(doc, answer)
    assert ("playbook_deviation", "max_term") in reason_codes(result)
    assert result["risk"] == "medium"
    assert not result["auto_approve"]


def test_quote_not_in_document_needs_review_with_zero_confidence(sample_doc):
    answer = sample_nda_answer(governing_law=cited("Delaware", 1, "governed by the laws of Delaware"))
    _, result = run(sample_doc, answer)
    assert ("field_unverified", "governing_law") in reason_codes(result)
    assert result["confidence"] == 0.0
    assert not result["auto_approve"]


def test_value_that_is_not_in_its_quote_needs_review(sample_doc):
    answer = sample_nda_answer(term_months=cited(24, 1, "shall remain in effect for six (6) months from the"))
    _, result = run(sample_doc, answer)
    assert ("value_not_in_quote", "term_months") in reason_codes(result)


def test_low_confidence_needs_review(sample_doc):
    answer = sample_nda_answer(mutual=cited(True, 1, "each Party may furnish the other Party with certain information", 0.6))
    _, result = run(sample_doc, answer)
    assert ("low_field_confidence", "mutual") in reason_codes(result)
    assert result["confidence"] == 0.6


def test_clause_called_absent_but_mentioned_needs_review():
    text = "Mutual Non-Disclosure Agreement. Neither party shall solicit the other's employees."
    doc = DocText(1, [PageText(1, text)])
    answer = sample_nda_answer()
    answer["classification"]["quote"] = "Mutual Non-Disclosure Agreement"
    _, result = run(doc, answer)
    assert ("absent_but_mentioned", "non_solicit_months") in reason_codes(result)


def test_prompt_injection_text_needs_review_and_is_high_risk():
    from common.pdf import parse_pdf
    from tests.conftest import FIXTURES

    doc = parse_pdf((FIXTURES / "injection_nda.pdf").read_bytes())
    answer = sample_nda_answer()
    answer["classification"]["quote"] = "Confidentiality and Non-Disclosure Agreement"
    _, result = run(doc, answer)
    assert ("suspected_prompt_injection", None) in reason_codes(result)
    assert result["risk"] == "high"
    assert not result["auto_approve"]


def test_non_nda_goes_to_review_as_not_an_nda(sample_doc):
    answer = {
        "classification": {
            "doc_type": "other", "subtype": "invoice", "confidence": 0.97, "page": 1,
            "quote": "Mutual Non-Disclosure Agreement",
        },
        "nda_fields": None,
    }
    _, result = run(sample_doc, answer)
    assert ("not_an_nda", None) in reason_codes(result)
    assert not result["auto_approve"]


def test_scanned_pdf_with_no_text_goes_to_review():
    doc = DocText(1, [PageText(1, "")])
    extraction = {"outcome": "no_text", "error": None, "classification": None, "fields": None}
    result = score_document(doc, extraction, RULES)
    assert ("no_text", None) in reason_codes(result)
    assert result["confidence"] == 0.0
    assert not result["auto_approve"]


def test_unusable_model_output_goes_to_review(sample_doc):
    extraction, result = run(sample_doc, "this is not json")
    assert extraction["outcome"] == "invalid_output"
    assert any(r["code"] == "extraction_failed" for r in result["reasons"])
    assert result["risk"] == "high"


def test_refusal_and_cutoff_are_not_exceptions(sample_doc):
    assert run(sample_doc, "", "refusal")[0]["outcome"] == "refused"
    assert run(sample_doc, "{", "max_tokens")[0]["outcome"] == "invalid_output"


def test_result_is_json_serialisable(sample_doc):
    _, result = run(sample_doc, sample_nda_answer())
    json.dumps(result)
