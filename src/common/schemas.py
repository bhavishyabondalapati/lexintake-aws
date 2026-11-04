"""What the model must return, as Pydantic models.

One response holds the classification and, if the document is an NDA, its cited fields. Every
field is `{value, page, quote, confidence}` because every value has to point at the text it came
from. (Adapted from LexIntake; this version extracts NDA fields only.)

Used by the extract Lambda only. The score Lambda reads the validated JSON and never imports
pydantic.
"""

import types
from datetime import date
from enum import StrEnum
from typing import Any, ClassVar, Literal, Union, get_args, get_origin

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    create_model,
    field_validator,
    model_validator,
)


class DocType(StrEnum):
    NDA = "nda"
    SIDE_LETTER = "side_letter"
    INVESTOR_NOTICE = "investor_notice"
    LEGAL_NOTICE = "legal_notice"
    OTHER = "other"


class Subtype(StrEnum):
    CAPITAL_CALL = "capital_call"
    DISTRIBUTION = "distribution"
    ANNUAL_MEETING = "annual_meeting"
    DEMAND_LETTER = "demand_letter"
    NOTICE_OF_BREACH = "notice_of_breach"
    SUBPOENA = "subpoena"
    INVOICE = "invoice"
    NEWSLETTER = "newsletter"
    BOARD_MINUTES = "board_minutes"
    MARKETING_FLYER = "marketing_flyer"


# Which subtypes each type has. NDAs and side letters have none (subtype is null).
SUBTYPES: dict[DocType, tuple[Subtype, ...]] = {
    DocType.NDA: (),
    DocType.SIDE_LETTER: (),
    DocType.INVESTOR_NOTICE: (Subtype.CAPITAL_CALL, Subtype.DISTRIBUTION, Subtype.ANNUAL_MEETING),
    DocType.LEGAL_NOTICE: (Subtype.DEMAND_LETTER, Subtype.NOTICE_OF_BREACH, Subtype.SUBPOENA),
    DocType.OTHER: (
        Subtype.INVOICE,
        Subtype.NEWSLETTER,
        Subtype.BOARD_MINUTES,
        Subtype.MARKETING_FLYER,
    ),
}

DATE = "Date in ISO format YYYY-MM-DD."
# A clause that is either there (true) or not (null).
TrueOrAbsent = Literal[True] | None


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NdaFields(Fields):
    counterparty: str = Field(
        description="The other party: the company the fund is signing with (not the fund side)."
    )
    fund_party: str = Field(
        description="The fund-side party: the fund (e.g. '... Fund III, L.P.') or its management "
        "company (e.g. '... Management, LLC')."
    )
    effective_date: date = Field(description=f"The effective date of the agreement. {DATE}")
    mutual: bool = Field(
        description="true if both parties disclose and protect information (a mutual NDA); false "
        "if only one side discloses. Quote the sentence that shows who discloses to whom."
    )
    term_months: int = Field(
        description="How long the confidentiality obligations last, in months (two (2) years = 24)."
    )
    governing_law: str = Field(
        description="The governing-law jurisdiction name only, e.g. 'Delaware', 'New York', "
        "'England and Wales', 'Cayman Islands' (not 'the State of Delaware')."
    )
    non_solicit_months: int | None = Field(
        description="Length of the non-solicitation (of employees) restriction in months; null "
        "if the agreement has no non-solicit clause."
    )
    non_compete_months: int | None = Field(
        description="Length of the non-competition restriction in months; null if there is no "
        "non-compete clause."
    )
    residuals_clause: TrueOrAbsent = Field(
        description="true if the agreement has a residuals clause (lets a party use information "
        "retained in unaided memory); null if it has none."
    )
    return_destroy_days: int | None = Field(
        description="Days allowed to return or destroy confidential information after a request; "
        "null if there is no return/destroy obligation."
    )


def is_optional(fields: type[Fields], name: str) -> bool:
    return type(None) in get_args(fields.model_fields[name].annotation)


def is_true_or_absent(fields: type[Fields], name: str) -> bool:
    return fields.model_fields[name].annotation == TrueOrAbsent


class Cited(BaseModel):
    """One extracted field with its evidence. `value` is typed per field by `cited_model()`."""

    model_config = ConfigDict(extra="forbid")

    value: Any = Field(description="The value, or null if the document doesn't contain it.")
    page: int | None = Field(
        description="1-based page number the quote is on; null if value is null."
    )
    quote: str | None = Field(
        description="The exact text from the document that states the value, copied character "
        "for character (one sentence or line is enough); null if value is null."
    )
    confidence: float = Field(
        ge=0, le=1, description="How sure you are that the value is right, from 0 to 1."
    )

    @model_validator(mode="after")
    def evidence_matches_value(self) -> "Cited":
        if self.value is None:
            self.page = None  # nothing to cite for an absent clause
            self.quote = None
        elif self.page is None or not (self.quote or "").strip():
            raise ValueError("a non-null value needs a page and a quote")
        return self

    @field_validator("page")
    @classmethod
    def page_exists(cls, page: int | None, info: ValidationInfo) -> int | None:
        page_count = (info.context or {}).get("page_count")
        if page is not None and (page < 1 or (page_count and page > page_count)):
            raise ValueError(f"page {page} is not in the document (1..{page_count})")
        return page


class CitedFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    FIELDS: ClassVar[type[Fields]]

    def cited(self) -> dict[str, Cited]:
        return {name: getattr(self, name) for name in type(self).model_fields}


def _api_type(annotation: Any) -> Any:
    """The value type the model is asked for. Always nullable: it may say "not found" for any
    field instead of guessing. TrueOrAbsent is asked as a boolean and false becomes null."""
    if annotation == TrueOrAbsent:
        return bool | None
    if get_origin(annotation) in (Union, types.UnionType):
        return annotation
    return annotation | None


def _false_means_absent(cls: type, value: Any) -> Any:
    return None if value is False else value


def _cited_field_class(fields: type[Fields], name: str) -> type[Cited]:
    info = fields.model_fields[name]
    validators = {}
    if is_true_or_absent(fields, name):
        validators["false_means_absent"] = field_validator("value")(_false_means_absent)
    return create_model(
        f"{fields.__name__.removesuffix('Fields')}_{name}",
        __base__=Cited,
        __validators__=validators,
        value=(_api_type(info.annotation), Field(description=info.description)),
    )


def cited_model(fields: type[Fields]) -> type[CitedFields]:
    """`CitedNdaFields`: the same keys as the value model, each wrapped in a Cited."""
    model = create_model(
        f"Cited{fields.__name__}",
        __base__=CitedFields,
        **{name: (_cited_field_class(fields, name), ...) for name in fields.model_fields},
    )
    model.FIELDS = fields
    return model


CitedNdaFields = cited_model(NdaFields)


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_type: DocType = Field(description="The document type.")
    subtype: Subtype | None = Field(
        description="The subtype; must be one of the subtypes listed for doc_type, or null for "
        "nda and side_letter."
    )
    confidence: float = Field(ge=0, le=1, description="How sure you are, from 0 to 1.")
    page: int = Field(description="1-based page of the quote.")
    quote: str = Field(
        description="Exact text from the document that shows its type, usually the title or "
        "opening line, copied character for character."
    )

    @model_validator(mode="after")
    def subtype_fits_type(self) -> "Classification":
        allowed = SUBTYPES[self.doc_type]
        if (self.subtype is None) != (not allowed) or (allowed and self.subtype not in allowed):
            raise ValueError(f"subtype {self.subtype} doesn't fit doc_type {self.doc_type}")
        return self

    @field_validator("page")
    @classmethod
    def page_exists(cls, page: int, info: ValidationInfo) -> int:
        page_count = (info.context or {}).get("page_count")
        if page < 1 or (page_count and page > page_count):
            raise ValueError(f"page {page} is not in the document (1..{page_count})")
        return page


class Extraction(BaseModel):
    """The whole answer of the single model call."""

    model_config = ConfigDict(extra="forbid")

    classification: Classification
    nda_fields: CitedNdaFields | None = Field(
        description="The NDA fields when doc_type is nda; null for every other document type."
    )

    @model_validator(mode="after")
    def fields_only_for_nda(self) -> "Extraction":
        is_nda = self.classification.doc_type == DocType.NDA
        if is_nda and self.nda_fields is None:
            raise ValueError("doc_type is nda, so nda_fields is required")
        if not is_nda:
            self.nda_fields = None
        return self
