"""Check what the model said against the parsed text. Nothing the model returns is trusted until it
passes here. (Adapted from LexIntake; works on plain dicts and has no OCR matching, so it needs
no third-party packages.)

For each field with a value:
1. the quote must exist in the document text;
2. the value must appear in its own quote (a real quote next to an invented value is caught here).

For NDA clauses the model calls absent (null) there is no quote to check, so a keyword scan looks
for the clause anyway. And a document that reads like an NDA but wasn't classified as one is
flagged, so an NDA can't slip past the extraction step by being misclassified.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from common.doctext import DocText, normalize
from common.nda import DATE_FIELDS, OPTIONAL_FIELDS

# Keywords that mean an NDA clause is there. If the model says the clause is absent but one of
# these is in the text, a person should look.
ABSENCE_KEYWORDS: dict[str, re.Pattern[str]] = {
    "non_solicit_months": re.compile(r"solicit", re.I),
    "non_compete_months": re.compile(r"non-?compet|not\s+(?:to\s+)?compete|competes\s+with", re.I),
    "residuals_clause": re.compile(r"residuals?\b|unaided\s+memory", re.I),
    "return_destroy_days": re.compile(
        r"return\s+or\s+destroy|destroy\s+or\s+return|return\s+and\s+destroy|destruction\s+of",
        re.I,
    ),
}

# Signs that a document is an NDA. Two or more different ones and a non-NDA classification ->
# needs review. One isn't enough: side letters often have a short confidentiality paragraph.
NDA_SIGNALS: dict[str, re.Pattern[str]] = {
    "defines_confidential_information": re.compile(
        r"\"?confidential information\"?\s+(?:means|shall\s+mean|includes)", re.I
    ),
    "non_disclosure": re.compile(r"non-?disclosure", re.I),
    "confidentiality_agreement": re.compile(
        r"confidentiality\s+(?:and\s+non-?disclosure\s+)?(?:agreement|undertaking)", re.I
    ),
    "evaluation_material": re.compile(r"evaluation\s+material", re.I),
    "return_or_destroy": ABSENCE_KEYWORDS["return_destroy_days"],
    "use_solely_to_evaluate": re.compile(r"solely\s+for\s+the\s+purpose\s+of\s+evaluating", re.I),
}
NDA_SIGNALS_MIN = 2

# Text addressed to an AI system inside a document. The main defence against prompt injection is
# structural (the model can't approve anything, and every value must be quoted from the document),
# but an attack can plant a fake value *in* the document and get it quoted. So a document that
# talks to "the AI" always goes to a person. A heuristic: it will miss some attacks.
INJECTION_SIGNALS: dict[str, re.Pattern[str]] = {
    "ignore_instructions": re.compile(
        r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:the\s+|any\s+)?(?:previous|prior|above|"
        r"earlier|preceding)\s+(?:instructions|prompts?|rules)",
        re.I,
    ),
    "addressed_to_ai": re.compile(
        r"\b(?:note|message|instructions?|reminder)\s+(?:to|for)\s+(?:the\s+|any\s+|all\s+)?"
        r"(?:ai|llm|model|assistant|chatbot|language\s+model|automated\s+reviewer)s?\b",
        re.I,
    ),
    "you_are_an_assistant": re.compile(
        r"\byou\s+are\s+(?:now\s+)?(?:an?|the)\s+(?:ai|assistant|language\s+model|llm|chatbot)\b",
        re.I,
    ),
    "fake_system_message": re.compile(
        r"\bsystem\s+(?:note|prompt|message)\b|<\s*/?\s*system\b", re.I
    ),
    "fake_prompt_tags": re.compile(r"<\s*/?\s*(?:document|page|instructions?)\b", re.I),
    "asks_for_approval": re.compile(
        r"\bmark\s+(?:it|this(?:\s+document|\s+agreement)?)\s+(?:as\s+)?approved\b|"
        r"\bset\s+(?:every|all|each)\s+confidences?\b",
        re.I,
    ),
}


@dataclass
class FieldCheck:
    name: str
    value: Any
    page: int | None
    quote: str | None
    confidence: float
    # verified | unverified (quote not found) | absent (null, clause may be absent) |
    # missing (null, but the field should always be there)
    status: str
    value_in_quote: bool | None = None  # None = can't be checked (yes/no fields)
    flags: list[str] = field(default_factory=list)
    keyword: str | None = None  # the keyword that set absent_but_mentioned

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def find_quote(doc: DocText, quote: str | None, cited_page: int | None) -> int | None:
    """The page the quote is on (the cited page first, then every other), or None."""
    q = normalize(quote or "")
    if not q:
        return None
    order = [cited_page] if cited_page and doc.page(cited_page) else []
    order += [p.number for p in doc.pages if p.number != cited_page]
    for number in order:
        if q in doc.page(number).norm_text:
            return number
    return None


# --- Is the value in its own quote? -------------------------------------------------------------

_ONES = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_MONTHS = (
    "january february march april may june july august september october november december"
).split()


def number_words(n: int) -> str | None:
    if 0 <= n < 20:
        return _ONES[n]
    if 20 <= n < 100:
        return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")
    if 100 <= n < 1000:
        rest = number_words(n % 100) if n % 100 else None
        return f"{_ONES[n // 100]} hundred" + (f" {rest}" if rest else "")
    return None


def _number_forms(n: int) -> list[str]:
    forms = [str(n)]
    if words := number_words(n):
        forms.append(words)
    return forms


def _int_forms(name: str, n: int) -> list[str]:
    forms = _number_forms(n)
    if name.endswith("_months") and n % 12 == 0:  # "two (2) years" supports 24 months
        forms += _number_forms(n // 12)
    return forms


def _date_forms(d: date) -> list[str]:
    month = _MONTHS[d.month - 1]
    return [
        d.isoformat(),
        f"{month} {d.day} {d.year}",
        f"{month[:3]} {d.day} {d.year}",
        f"{d.day} {month} {d.year}",
        f"{d.month}/{d.day}/{d.year}",
        f"{d.month:02d}/{d.day:02d}/{d.year}",
    ]


def _simplify(text: str) -> str:
    """Lower case, no commas or full stops after month abbreviations, no 1st/2nd/3rd/4th."""
    text = re.sub(r"(?<=\d),(?=\d{3})", "", normalize(text))  # 1,250,000 -> 1250000
    text = text.casefold().replace(",", " ")
    text = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", text)
    text = re.sub(r"\b([a-z]{3})\.", r"\1", text)
    return re.sub(r"\s+", " ", text)


def value_in_quote(name: str, value: Any, quote: str) -> bool | None:
    q = _simplify(quote)
    if isinstance(value, bool):
        return None  # a yes/no about the whole clause; the quote is checked, the value can't be
    if name in DATE_FIELDS and isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            return False
    if isinstance(value, int):
        for form in map(_simplify, _int_forms(name, value)):
            # Digits must not be part of a longer number; words must be whole words.
            pattern = (
                rf"(?<!\d){re.escape(form)}(?!\d)"
                if form[0].isdigit()
                else rf"\b{re.escape(form)}\b"
            )
            if re.search(pattern, q):
                return True
        return False
    if isinstance(value, date):
        return any(_simplify(f) in q for f in _date_forms(value))
    if isinstance(value, str):
        return _simplify(value) in q
    return None


# --- Whole-result checks ------------------------------------------------------------------------


def check_fields(doc: DocText, fields: dict[str, dict]) -> list[FieldCheck]:
    return [_check_field(doc, name, cited) for name, cited in fields.items()]


def _check_field(doc: DocText, name: str, cited: dict) -> FieldCheck:
    value, quote, page = cited.get("value"), cited.get("quote"), cited.get("page")
    check = FieldCheck(name, value, page, quote, cited.get("confidence", 0.0), "absent")
    if value is None:
        if name not in OPTIONAL_FIELDS:
            check.status = "missing"
        elif name in ABSENCE_KEYWORDS:
            if m := ABSENCE_KEYWORDS[name].search(doc.norm_text):
                check.flags.append("absent_but_mentioned")
                check.keyword = m.group(0)
        return check

    found_page = find_quote(doc, quote, page)
    if found_page is None:
        check.status = "unverified"
        return check
    check.status = "verified"
    if found_page != page:
        check.flags.append("page_mismatch")
        check.page = found_page  # point at where the text really is
    check.value_in_quote = value_in_quote(name, value, quote or "")
    return check


def check_classification(doc: DocText, c: dict) -> FieldCheck:
    found_page = find_quote(doc, c.get("quote"), c.get("page"))
    check = FieldCheck(
        "classification",
        c["doc_type"],
        found_page or c.get("page"),
        c.get("quote"),
        c.get("confidence", 0.0),
        "verified" if found_page is not None else "unverified",
    )
    if found_page is not None and found_page != c.get("page"):
        check.flags.append("page_mismatch")
    return check


def nda_signals(doc: DocText) -> list[str]:
    """Which NDA signals the text contains."""
    return [name for name, pattern in NDA_SIGNALS.items() if pattern.search(doc.norm_text)]


def injection_signals(doc: DocText) -> list[str]:
    """Which kinds of AI-directed instructions the text contains."""
    return [name for name, pattern in INJECTION_SIGNALS.items() if pattern.search(doc.norm_text)]
