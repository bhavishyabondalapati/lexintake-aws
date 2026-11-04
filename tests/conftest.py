"""Shared test setup: puts src/ on the path (as the Lambda package does) and provides a fake model
so no test ever calls the Anthropic API or AWS."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from common.llm import LlmResponse  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class FakeExtractor:
    """Returns a canned answer. Records the prompts it was given."""

    def __init__(self, payload: dict | str, stop_reason: str = "end_turn"):
        self.text = payload if isinstance(payload, str) else json.dumps(payload)
        self.stop_reason = stop_reason
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int) -> LlmResponse:
        self.calls.append((system, user))
        return LlmResponse(
            text=self.text,
            stop_reason=self.stop_reason,
            model="fake-model",
            input_tokens=100,
            output_tokens=50,
        )


def cited(value, page, quote, confidence=0.95):
    return {"value": value, "page": page, "quote": quote, "confidence": confidence}


def absent(confidence=0.95):
    return cited(None, None, None, confidence)


EFFECTIVE = (
    'This Mutual Non-Disclosure Agreement (this "Agreement") is entered into as of April 14, 2022'
)


def sample_nda_answer(**overrides) -> dict:
    """What a good model would say about tests/fixtures/sample_nda.pdf (a standard-position NDA)."""
    fields = {
        "counterparty": cited("Dalton Foods LLC", 1, "Kestrel Ridge Capital Management, LLC and Dalton Foods LLC"),
        "fund_party": cited("Kestrel Ridge Capital Management, LLC", 1, "Kestrel Ridge Capital Management, LLC and Dalton Foods LLC"),
        "effective_date": cited("2022-04-14", 1, EFFECTIVE),
        "mutual": cited(True, 1, "each Party may furnish the other Party with certain information concerning its"),
        "term_months": cited(6, 1, "shall remain in effect for six (6) months from the"),
        "governing_law": cited("New York", 1, "laws of the State of New York"),
        "non_solicit_months": absent(),
        "non_compete_months": absent(),
        "residuals_clause": absent(),
        "return_destroy_days": cited(45, 1, "Within forty-five (45) days after a written request by the disclosing"),
    }
    fields.update(overrides)
    return {
        "classification": {
            "doc_type": "nda",
            "subtype": None,
            "confidence": 0.98,
            "page": 1,
            "quote": "Mutual Non-Disclosure Agreement",
        },
        "nda_fields": fields,
    }


@pytest.fixture
def sample_pdf() -> bytes:
    return (FIXTURES / "sample_nda.pdf").read_bytes()


@pytest.fixture
def sample_doc(sample_pdf):
    from common.pdf import parse_pdf

    return parse_pdf(sample_pdf)
