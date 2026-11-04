"""NDA playbook: load the rules from YAML and check an NDA's extracted fields against them.
(Adapted from LexIntake; plain dataclasses instead of pydantic.)

Each rule is pass / deviation / unknown. Only a verified value (or a verified absence) is judged;
anything the checker can't trust is `unknown`, never a pass.
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

PASS, DEVIATION, UNKNOWN = "pass", "deviation", "unknown"
CHECKS = {"max", "one_of", "absent", "present"}


@dataclass(frozen=True)
class Rule:
    id: str
    field: str
    check: str
    limit: int | None = None
    allowed: list[str] = field(default_factory=list)
    description: str = ""
    label: str = ""  # short name of what a deviation looks like, e.g. "Term > 24 months"

    def __post_init__(self) -> None:
        if self.check not in CHECKS:
            raise ValueError(f"rule {self.id!r}: unknown check {self.check!r}")
        if self.check == "max" and self.limit is None:
            raise ValueError(f"rule {self.id!r}: check 'max' needs a 'limit'")
        if self.check == "one_of" and not self.allowed:
            raise ValueError(f"rule {self.id!r}: check 'one_of' needs a non-empty 'allowed' list")

    def passes(self, value: Any) -> bool:
        """Null means the clause is absent from the document."""
        match self.check:
            case "max":
                return value is None or value <= self.limit
            case "one_of":
                return value in self.allowed
            case "absent":
                return value is None
            case "present":
                return value is not None
        return False


def load_playbook(path: str | Path) -> list[Rule]:
    data = yaml.safe_load(Path(path).read_text())
    rules = [
        Rule(
            id=r["id"],
            field=r["field"],
            check=r["check"],
            limit=r.get("limit"),
            allowed=r.get("allowed") or [],
            description=r.get("description", ""),
            label=r.get("label") or r["id"].replace("_", " "),
        )
        for r in data["rules"]
    ]
    if len({r.id for r in rules}) != len(rules):
        raise ValueError("playbook rule ids must be unique")
    return rules


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    label: str
    field: str
    outcome: str  # pass | deviation | unknown
    value: Any
    page: int | None
    quote: str | None
    reason: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _untrusted_reason(check: dict[str, Any] | None) -> str | None:
    """Why this extracted field can't be relied on, or None if it can."""
    if check is None:
        return "field was not extracted"
    status = check.get("status")
    if status == "unverified":
        return "the quote for this field was not found in the document"
    if status == "missing":
        return "a required field was left empty"
    if status not in ("verified", "absent"):
        return f"unrecognised field status {status!r}"
    if status == "verified" and check.get("value_in_quote") is False:
        return "the value does not appear in its quote"
    if "absent_but_mentioned" in (check.get("flags") or []):
        return "marked absent, but the text mentions this clause"
    return None


def _describe(rule: Rule, value: Any) -> str:
    match rule.check:
        case "max":
            return f"{value} vs limit {rule.limit}" if value is not None else "no such clause"
        case "one_of":
            return f"{value!r} vs allowed {rule.allowed}"
        case "absent":
            return "clause must not be present"
        case "present":
            return "clause must be present"
    return ""


def _check_rule(rule: Rule, check: dict[str, Any] | None) -> RuleResult:
    value = check.get("value") if check else None
    page = check.get("page") if check else None
    quote = check.get("quote") if check else None

    def result(outcome: str, reason: str) -> RuleResult:
        return RuleResult(rule.id, rule.label, rule.field, outcome, value, page, quote, reason)

    doubt = _untrusted_reason(check)
    if doubt:
        return result(UNKNOWN, doubt)
    if value is None and rule.check == "one_of":
        return result(UNKNOWN, "no value to compare with the allowed list")
    if rule.passes(value):
        return result(PASS, _describe(rule, value))
    return result(DEVIATION, _describe(rule, value))


def check_playbook(rules: list[Rule], checks: dict[str, dict[str, Any]]) -> list[RuleResult]:
    """One result per rule, in playbook order. `checks` maps field name -> a FieldCheck as a dict
    (status, value, value_in_quote, flags, ...)."""
    return [_check_rule(rule, checks.get(rule.field)) for rule in rules]
