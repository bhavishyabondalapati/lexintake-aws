"""A parsed document as text, page by page, plus the one normalisation used everywhere.

The prompt is built from this, and every quote the model returns is checked against it, so the
model and the checker always see the same text. (Adapted from LexIntake; this version has no
OCR and no text blocks, only pages.)
"""

import re
import unicodedata
from dataclasses import dataclass, field

# The prompt replaces < and > in document text with these look-alikes, so a document can't close
# or fake the <document> tag around it. Quotes come back with them, so they are turned back into
# < and > before any comparison.
ESCAPES = {"<": "‹", ">": "›"}
UNESCAPES = {v: k for k, v in ESCAPES.items()}

_TRANSLATE = str.maketrans(
    {
        **UNESCAPES,
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        " ": " ",
    }
)
_SPACE = re.compile(r"\s+")
# Parsers sometimes extract "<notices@x>" as "< notices@x>"; spacing just inside angle brackets
# doesn't matter for matching.
_INSIDE_BRACKETS = re.compile(r"(?<=<)\s+|\s+(?=>)")


def normalize(text: str) -> str:
    """Unescape, NFKC (ligatures, full-width), straight quotes and dashes, one space."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE)
    return _INSIDE_BRACKETS.sub("", _SPACE.sub(" ", text)).strip()


def escape(text: str) -> str:
    return text.replace("<", ESCAPES["<"]).replace(">", ESCAPES[">"])


@dataclass
class PageText:
    number: int  # 1-based
    raw_text: str  # what the model sees

    @property
    def norm_text(self) -> str:
        return normalize(self.raw_text)


@dataclass
class DocText:
    page_count: int  # pages in the file (may be more than len(pages) when partial)
    pages: list[PageText] = field(default_factory=list)
    partial: bool = False  # not every page was read (too many pages, or a page failed)

    def page(self, number: int) -> PageText | None:
        return self.pages[number - 1] if 1 <= number <= len(self.pages) else None

    @property
    def norm_text(self) -> str:
        return " ".join(p.norm_text for p in self.pages).strip()

    def to_json(self) -> dict:
        return {
            "page_count": self.page_count,
            "partial": self.partial,
            "pages": [{"number": p.number, "text": p.raw_text} for p in self.pages],
        }

    @classmethod
    def from_json(cls, data: dict) -> "DocText":
        return cls(
            page_count=data["page_count"],
            partial=data.get("partial", False),
            pages=[PageText(p["number"], p["text"]) for p in data["pages"]],
        )
