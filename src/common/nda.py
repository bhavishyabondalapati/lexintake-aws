"""Plain constants about NDA fields, shared by code that must not import pydantic (the score
Lambda). tests/test_schemas.py checks they match `common.schemas.NdaFields`."""

# Fields where null is a normal answer: the agreement may simply not have the clause.
OPTIONAL_FIELDS = frozenset(
    {"non_solicit_months", "non_compete_months", "residuals_clause", "return_destroy_days"}
)

# Fields whose value is a date (the model returns them as YYYY-MM-DD strings).
DATE_FIELDS = frozenset({"effective_date"})
