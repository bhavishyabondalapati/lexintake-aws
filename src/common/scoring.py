"""Scoring: confidence, risk and the reasons a person must look at a document. (Adapted from
LexIntake's routing rules.)

A document is auto-approved only when there is no reason at all to send it to a person. The
model's confidence is one input, never the only one: a confident answer whose quote can't be found
still goes to review.

- confidence: the lowest confidence among the classification and every field. A field or
  classification whose quote could not be verified in the document counts as 0.
- risk: "high" if the document talks to the AI, the model's answer was unusable, or the playbook
  has two or more deviations; "medium" for one deviation, anything the playbook could not check, or
  a document that is not an NDA; otherwise "low".
- reasons: every concrete problem found. No reasons + confidence >= 0.8 + risk low = auto-approve
  (the state machine's Choice state makes that decision from these three numbers).
"""

from dataclasses import asdict, dataclass
from typing import Any

from common import verify
from common.doctext import DocText
from common.playbook import DEVIATION, UNKNOWN, Rule, check_playbook

MIN_CONFIDENCE = 0.8
AUTO_APPROVE_RISK = "low"


@dataclass(frozen=True)
class Reason:
    code: str
    field: str | None = None
    detail: str = ""

    def to_json(self) -> dict:
        return asdict(self)


def score_document(
    doc: DocText, extraction: dict[str, Any], rules: list[Rule], min_confidence: float = MIN_CONFIDENCE
) -> dict[str, Any]:
    reasons: list[Reason] = []
    risk_high = False

    # --- the document itself ---
    if doc.partial:
        reasons.append(Reason("partial_parse", detail="not every page was read"))
    if not doc.norm_text:
        reasons.append(
            Reason("no_text", detail="no text layer found (a scan?); OCR is not part of this build")
        )
    injection = verify.injection_signals(doc)
    if injection:
        # The text talks to an AI system. Whatever the model answered, a person should look.
        reasons.append(Reason("suspected_prompt_injection", detail=", ".join(injection)))
        risk_high = True

    result: dict[str, Any] = {
        "doc_type": None,
        "confidence": 0.0,
        "risk": "high",
        "checks": [],
        "playbook": [],
        "injection_signals": injection,
    }

    # --- the model's answer ---
    if extraction["outcome"] == "no_text":
        pass  # the model was never called; "no_text" is already a reason
    elif extraction["outcome"] != "ok":
        reasons.append(Reason("extraction_failed", detail=f"{extraction['outcome']}: {extraction['error']}"))
        risk_high = True

    classification = extraction.get("classification")
    if classification is None:
        return _finish(result, reasons, risk="high")

    result["doc_type"] = classification["doc_type"]
    class_check = verify.check_classification(doc, classification)
    confidences = [0.0 if class_check.status != "verified" else class_check.confidence]
    if classification["confidence"] < min_confidence:
        reasons.append(
            Reason(
                "low_classification_confidence",
                detail=f"{classification['confidence']:.2f} < {min_confidence}",
            )
        )
    if class_check.status != "verified":
        reasons.append(Reason("classification_unverified", detail="quote not found in the text"))
    signals = verify.nda_signals(doc)
    if classification["doc_type"] != "nda" and len(signals) >= verify.NDA_SIGNALS_MIN:
        # The NDA guard: an NDA misclassified as something else would skip the NDA checks.
        reasons.append(Reason("nda_signals_but_not_nda", detail=", ".join(signals)))

    # --- not an NDA: nothing more is extracted in this build ---
    if classification["doc_type"] != "nda":
        sub = f" ({classification['subtype']})" if classification["subtype"] else ""
        reasons.append(Reason("not_an_nda", detail=f"{classification['doc_type']}{sub}"))
        result["confidence"] = min(confidences)
        result["checks"] = [class_check.to_json()]
        return _finish(result, reasons, risk="high" if risk_high else "medium")

    # --- NDA fields ---
    checks = verify.check_fields(doc, extraction["fields"])
    for c in checks:
        confidences.append(0.0 if c.status in ("unverified", "missing") else c.confidence)
        reasons.extend(_field_reasons(c, min_confidence))

    playbook_results = check_playbook(rules, {c.name: c.to_json() for c in checks})
    deviations = [r for r in playbook_results if r.outcome == DEVIATION]
    unknowns = [r for r in playbook_results if r.outcome == UNKNOWN]
    for r in deviations:
        reasons.append(Reason("playbook_deviation", r.rule_id, r.reason))
    for r in unknowns:
        # A rule nobody could check must not look like a rule that was met.
        reasons.append(Reason("playbook_unknown", r.rule_id, r.reason))

    if risk_high or len(deviations) >= 2:
        risk = "high"
    elif deviations or unknowns:
        risk = "medium"
    else:
        risk = "low"

    result["confidence"] = min(confidences)
    result["checks"] = [class_check.to_json(), *(c.to_json() for c in checks)]
    result["playbook"] = [r.to_json() for r in playbook_results]
    return _finish(result, reasons, risk=risk)


def _field_reasons(c: verify.FieldCheck, min_confidence: float) -> list[Reason]:
    reasons = []
    if c.status == "unverified":
        reasons.append(Reason("field_unverified", c.name, "quote not found in the text"))
    elif c.status == "missing":
        reasons.append(Reason("field_missing", c.name, "required field left empty"))
    elif c.status == "verified" and c.value_in_quote is False:
        reasons.append(Reason("value_not_in_quote", c.name, f"{c.value} not in quote"))
    if c.status != "missing" and c.confidence < min_confidence:
        reasons.append(Reason("low_field_confidence", c.name, f"{c.confidence:.2f} < {min_confidence}"))
    if "absent_but_mentioned" in c.flags:
        reasons.append(
            Reason("absent_but_mentioned", c.name, f"model says absent; text has {c.keyword!r}")
        )
    return reasons


def _finish(result: dict, reasons: list[Reason], risk: str) -> dict:
    result["risk"] = risk
    result["reasons"] = [r.to_json() for r in reasons]
    result["reason_count"] = len(reasons)
    result["confidence"] = round(result["confidence"], 3)
    result["auto_approve"] = (
        not reasons and result["confidence"] >= MIN_CONFIDENCE and risk == AUTO_APPROVE_RISK
    )
    return result
