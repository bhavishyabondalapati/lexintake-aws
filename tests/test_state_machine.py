"""Structure checks on the Step Functions definition. (AWS's own validator can't be called from
this account, so these catch typos in state names and the retry/catch rules locally.)"""

import json
import re

from tests.conftest import ROOT

VALUES = {
    "table_name": "table",
    "dlq_url": "https://sqs.us-east-1.amazonaws.com/123456789012/dlq",
    "parse_arn": "arn:parse",
    "extract_arn": "arn:extract",
    "score_arn": "arn:score",
    "review_request_arn": "arn:review",
}


def load() -> dict:
    text = (ROOT / "statemachine" / "pipeline.asl.json.tftpl").read_text()
    return json.loads(re.sub(r"\$\{(\w+)\}", lambda m: VALUES[m.group(1)], text))


def targets(state: dict) -> list[str]:
    out = [state["Next"]] if "Next" in state else []
    out += [c["Next"] for c in state.get("Catch", [])]
    out += [c["Next"] for c in state.get("Choices", [])]
    out += [state["Default"]] if "Default" in state else []
    return out


def test_every_target_exists_and_every_state_is_reachable():
    sm = load()
    states = sm["States"]
    assert sm["StartAt"] in states
    seen, todo = set(), [sm["StartAt"]]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for t in targets(states[name]):
            assert t in states, f"{name} points at missing state {t}"
            todo.append(t)
    assert seen == set(states)
    for name, state in states.items():
        if state["Type"] not in ("Succeed", "Fail", "Choice"):
            assert "Next" in state, f"{name} has no Next"


def test_lambda_steps_retry_with_backoff_and_catch_to_the_dlq():
    states = load()["States"]
    for name in ("ParseDocument", "ExtractFields", "ScoreDocument"):
        retry = states[name]["Retry"][0]
        assert "TransientError" in retry["ErrorEquals"]
        assert retry["BackoffRate"] >= 2 and retry["MaxAttempts"] >= 3
        assert states[name]["Catch"][0] == {
            "ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "HandleFailure",
        }
    assert states["HandleFailure"]["Resource"] == "arn:aws:states:::sqs:sendMessage"
    assert states["HandleFailure"]["Next"] == "MarkFailed"
    assert states["Failed"]["Type"] == "Fail"


def test_choice_auto_approves_only_on_all_three_conditions():
    choice = load()["States"]["IsAutoApprove"]
    (rule,) = choice["Choices"]
    assert rule["Next"] == "WriteAutoApproved"
    assert {c["Variable"] for c in rule["And"]} == {
        "$.score.score.confidence", "$.score.score.risk", "$.score.score.reason_count",
    }
    assert choice["Default"] == "RequestHumanReview"


def test_human_review_waits_for_a_token_and_handles_every_outcome():
    state = load()["States"]["RequestHumanReview"]
    assert state["Resource"].endswith("lambda:invoke.waitForTaskToken")
    assert state["Parameters"]["Payload"]["task_token.$"] == "$$.Task.Token"
    assert state["TimeoutSeconds"] == 604800
    routes = [(c["ErrorEquals"][0], c["Next"]) for c in state["Catch"]]
    # specific errors first, States.ALL last (the first matching Catch wins)
    assert routes == [
        ("ReviewRejected", "WriteRejected"),
        ("States.Timeout", "WriteExpired"),
        ("States.ALL", "HandleFailure"),
    ]
    assert state["Next"] == "WriteApproved"


def test_final_statuses_are_written_to_dynamodb():
    states = load()["States"]
    expected = {
        "WriteAutoApproved": "auto_approved", "WriteApproved": "approved",
        "WriteRejected": "rejected", "WriteExpired": "expired",
    }
    for name, status in expected.items():
        values = states[name]["Parameters"]["ExpressionAttributeValues"]
        assert values[":s"] == {"S": status}
        assert states[name]["Next"] == "Done"
